"""The upload pipeline: ingest -> extract -> validate/merge.

One call to run() always produces a complete plan when the PDF is readable:
- keyword mode: the keyword plan.
- LLM mode: the LLM plan, with keyword results filling what the LLM left empty.
- LLM mode, LLM unusable: the keyword plan plus a visible warning (fallback).

It also records how long each stage took. Timings and failure reasons are
logged; protocol text, file names and provider responses never are.
"""

from __future__ import annotations

import logging
import random
import time
from dataclasses import dataclass, field
from typing import Dict, Optional

from config import Settings, get_settings
from extract import ParsedDocument, parse_pdf
from extractor import Extractor, KeywordExtractor
from models import ExtractionInfo, OperationalPlan

log = logging.getLogger("cora.pipeline")

SECTIONS = ("visits", "procedures", "staffing", "safety", "billing", "equipment", "pharmacy", "technology")
# Header fields the keyword extractor can supply when the LLM leaves them null.
HEADER_FILL = ("title", "short_title", "registry_id", "protocol_number", "phase", "sponsor", "design", "enrollment")

# Longest we will sleep before the one retry, even if the provider asks for more.
MAX_BACKOFF_SECONDS = 5.0
# The LLM extractor refuses to start a call with less time than this left.
MIN_CALL_SECONDS = 5.0

# Indirection so tests can replace sleeping with a no-op.
_sleep = time.sleep


@dataclass
class Timings:
    """Milliseconds spent in each stage of one upload."""

    ingest_ms: float = 0.0
    extract_ms: float = 0.0
    validate_ms: float = 0.0
    pages: int = 0
    ocr_pages: int = 0
    method: str = ""
    fallback: bool = False
    reason: Optional[str] = None
    attempts: int = 0

    def as_log_fields(self) -> Dict[str, object]:
        return {
            "pages": self.pages,
            "ocr_pages": self.ocr_pages,
            "method": self.method,
            "fallback": self.fallback,
            "reason": self.reason or "-",
            "llm_attempts": self.attempts,
            "ingest_ms": round(self.ingest_ms),
            "extract_ms": round(self.extract_ms),
            "validate_ms": round(self.validate_ms),
        }


@dataclass
class Result:
    plan: OperationalPlan
    timings: Timings = field(default_factory=Timings)


def _items(plan: OperationalPlan, key: str) -> list:
    if key == "pharmacy":
        return plan.pharmacy.items if plan.pharmacy else []
    return getattr(plan, key)


def _section_methods(plan: OperationalPlan, method: str, overrides: Optional[Dict[str, str]] = None) -> Dict[str, str]:
    out = {key: (method if _items(plan, key) else "none") for key in SECTIONS}
    out.update(overrides or {})
    return out


def merge(llm_plan: OperationalPlan, keyword_plan: OperationalPlan) -> Dict[str, str]:
    """Fill gaps in the LLM plan from the keyword plan, in place.

    The LLM plan is primary. Keyword results are only used where the LLM gave
    nothing, and items are copied unchanged, so their source page, confidence
    and "Found by keyword" notes are preserved. Returns which sections were
    filled, for the extraction metadata.
    """
    filled: Dict[str, str] = {}
    for name in HEADER_FILL:
        if getattr(llm_plan.protocol, name) in (None, ""):
            setattr(llm_plan.protocol, name, getattr(keyword_plan.protocol, name))

    # The minimum-success sections (visits, procedures, staffing) are not
    # filled: the keyword extractor has no visits or staffing, and its
    # procedure list has no visit links, so an empty LLM result there stays
    # empty and flagged.
    for key in ("safety", "equipment", "technology"):
        if not getattr(llm_plan, key) and getattr(keyword_plan, key):
            setattr(llm_plan, key, list(getattr(keyword_plan, key)))
            filled[key] = "keyword"
    if llm_plan.pharmacy is None and keyword_plan.pharmacy is not None:
        llm_plan.pharmacy = keyword_plan.pharmacy
        if keyword_plan.pharmacy.items:
            filled["pharmacy"] = "keyword"
    return filled


def _extract_with_retry(extractor: Extractor, parsed: ParsedDocument, deadline: Optional[float], timings: Timings):
    """Call the LLM extractor, retrying once if the failure is temporary.

    Why only once: a retry doubles the wait, and the user is watching a
    progress screen. Why only for some errors: a timeout, a 429 or a 5xx may
    succeed moments later, but a bad key or unreadable output will fail the
    same way again, so retrying just wastes time and money.
    """
    from llm_extractor import LLMError  # local import keeps keyword mode SDK-free

    for attempt in (1, 2):
        timings.attempts = attempt
        try:
            return extractor.extract(parsed, deadline=deadline)
        except LLMError as err:
            if not err.retryable or attempt == 2:
                raise
            # Backoff: wait a little so a brief overload can clear. The random
            # part (jitter) stops many clients retrying at the same instant.
            wait = min(err.retry_after or (1.0 + random.random()), MAX_BACKOFF_SECONDS)
            # Skip the retry if, after waiting, there wouldn't be time for a
            # useful call before the request's deadline.
            if deadline is not None and time.monotonic() + wait + MIN_CALL_SECONDS >= deadline:
                raise
            log.warning("llm_retry reason=%s status=%s request_id=%s", err.reason, err.status, err.request_id)
            _sleep(wait)


def run(
    data: bytes,
    filename: str,
    extractor: Extractor,
    settings: Optional[Settings] = None,
    deadline: Optional[float] = None,
) -> Result:
    """Process one uploaded PDF. Raises extract.ExtractionError for unusable PDFs."""
    settings = settings or get_settings()
    timings = Timings(method=extractor.name)

    # --- ingest: bytes -> page texts (with page cap and OCR) ---
    t = time.perf_counter()
    parsed = parse_pdf(
        data, filename, max_pages=settings.max_pages, max_ocr_pages=settings.max_ocr_pages, deadline=deadline
    )
    timings.ingest_ms = (time.perf_counter() - t) * 1000
    timings.pages, timings.ocr_pages = len(parsed.pages), parsed.ocr_pages

    # --- extract ---
    t = time.perf_counter()
    keyword = KeywordExtractor()
    llm_plan: Optional[OperationalPlan] = None
    info = ExtractionInfo(method="keyword", ocr_pages=parsed.ocr_pages)

    if extractor.name == keyword.name:
        plan = extractor.extract(parsed, deadline=deadline)
    else:
        # Always build the keyword plan too: it is fast, and it is both the
        # gap-filler when the LLM works and the fallback when it doesn't.
        plan = keyword.extract(parsed)
        try:
            llm_plan = _extract_with_retry(extractor, parsed, deadline, timings)
        except Exception as err:
            # LLMError carries a safe reason code. Anything else is a bug in
            # our own code; log only its type, because exception messages can
            # contain provider responses or protocol text.
            reason = getattr(err, "reason", "unexpected")
            warning = getattr(err, "user_message", None)
            if warning is None:
                from llm_extractor import WARNINGS

                warning = WARNINGS["unexpected"]
            log.warning(
                "llm_fallback reason=%s status=%s request_id=%s error_type=%s",
                reason, getattr(err, "status", None), getattr(err, "request_id", None), type(err).__name__,
            )
            info = ExtractionInfo(
                method="keyword", fallback=True, reason=reason, warning=warning, ocr_pages=parsed.ocr_pages
            )
            timings.fallback, timings.reason = True, reason
    timings.extract_ms = (time.perf_counter() - t) * 1000

    # --- validate + merge ---
    t = time.perf_counter()
    if llm_plan is not None:
        filled = merge(llm_plan, plan)
        info = ExtractionInfo(
            method=extractor.name,
            model=getattr(extractor, "model", None),
            sections=_section_methods(llm_plan, extractor.name, filled),
            ocr_pages=parsed.ocr_pages,
        )
        plan = llm_plan
    else:
        info.sections = _section_methods(plan, "keyword")
    plan.extraction = info.method
    plan.extraction_info = info
    # Re-validate after merging, so nothing invalid can reach the frontend.
    plan = OperationalPlan.model_validate(plan.model_dump())
    timings.validate_ms = (time.perf_counter() - t) * 1000
    timings.method = info.method

    return Result(plan=plan, timings=timings)
