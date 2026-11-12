"""Claude-based extractor. The only module that imports the Anthropic SDK.

Flow: page-numbered protocol text -> one Claude request with a structured
output schema (llm_schema.LLMPlan) -> every item re-checked in code -> a
validated models.OperationalPlan.

Two rules from the project spec shape this file:
- The LLM must not invent values. The prompt says so, and the code enforces
  what it can: pages must exist, uncertain items are forced below the review
  threshold, bad references are removed. A prompt alone is a request, not a
  guarantee.
- Protocol text and provider responses never go to logs or to the user.
  Failures are reduced to a short reason code (LLMError.reason).
"""

from __future__ import annotations

import time
from typing import Any, Callable, List, Optional, Tuple

import anthropic
from pydantic import BaseModel, ValidationError

from config import ConfigError, Settings
from extract import ParsedDocument, find_registry_id
from llm_schema import LLMPlan
from models import (
    BillingItem,
    EquipmentItem,
    OperationalPlan,
    Pharmacy,
    PharmacyItem,
    Procedure,
    ProtocolMetadata,
    ReviewFlag,
    SafetyReport,
    SectionReviews,
    StaffingRole,
    TechnologyItem,
    Visit,
)

# Matches reviewThreshold in the frontend: below this, a human must review.
REVIEW_THRESHOLD = 0.7
# What "uncertain" items are capped to, so they are always flagged.
CAPPED = 0.69
# Enough for a large plan; small enough that a non-streaming request finishes
# inside the timeout.
MAX_OUTPUT_TOKENS = 16000
# About 500K tokens. Far above any 150-page protocol; a guard so that an
# over-long input fails clearly instead of being cut off silently.
MAX_INPUT_CHARS = 2_000_000

CORE_SECTIONS = ("visits", "procedures", "staffing")

SYSTEM_PROMPT = """\
You extract operational requirements from a clinical trial protocol so that a \
research site can plan how to run the study. A coordinator will review your \
output against the protocol, so accuracy and honesty about uncertainty matter \
more than completeness.

The protocol is given page by page inside <page n="N"> tags. N is the page number.

Rules:
1. Report only what the protocol states. Never fill a gap with what is typical \
for trials of this kind. If something is not stated, use null or an empty list.
2. For every item give source_page: the page where it is stated. If you cannot \
point to a page, use null.
3. For every item give confidence from 0 to 1. Use 0.9 or more only when the \
protocol states it explicitly. Use less than 0.7 when you inferred it, when the \
text is ambiguous, or when sources in the protocol disagree, and explain why in notes.
4. Visits: list every scheduled visit from the schedule of activities in order, \
with ids V1, V2, ... Copy timing and windows as written.
5. Procedures: list each required procedure once, and in visits give the ids of \
the visits where the schedule of activities marks it. If you cannot tell which \
visits, leave visits empty and lower the confidence.
6. Staffing: list roles the protocol says are needed and any qualifications, \
training or certifications it requires. Give fte only if the protocol states a \
number; otherwise null. Do not estimate effort.
7. Do not include any information about individual participants.
"""

# Fixed, safe sentences for each failure. The user sees these; they never
# contain the provider's response, the key, or protocol text.
WARNINGS = {
    "timeout": "The AI service took too long to respond, so this plan was built by keyword search only. Try again in a few minutes.",
    "rate_limited": "The AI service is receiving too many requests right now, so this plan was built by keyword search only. Try again in a few minutes.",
    "connection": "CORA couldn't reach the AI service, so this plan was built by keyword search only. Check the server's internet connection and try again.",
    "provider_error": "The AI service had a temporary problem, so this plan was built by keyword search only. Try again in a few minutes.",
    "invalid_key": "The AI service rejected CORA's API key, so this plan was built by keyword search only. Ask your administrator to check LLM_API_KEY on the server.",
    "rejected": "The AI service rejected the request, so this plan was built by keyword search only. Ask your administrator to check the model name (LLM_MODEL) and the account's access.",
    "invalid_output": "The AI service returned a plan CORA couldn't read, so this plan was built by keyword search only. Try uploading again.",
    "refused": "The AI service declined to process this document, so this plan was built by keyword search only.",
    "truncated": "The AI service's answer was cut off before it finished, so this plan was built by keyword search only. Try uploading again.",
    "too_long": "This protocol has too much text for the AI service, so this plan was built by keyword search only. Remove appendices and upload again.",
    "deadline": "There wasn't enough time left to use the AI service, so this plan was built by keyword search only. Try again.",
    "unexpected": "Something went wrong while using the AI service, so this plan was built by keyword search only. Try again, and tell your administrator if it keeps happening.",
}


class LLMError(Exception):
    """An LLM call failed. Carries a reason code, never the provider's text."""

    def __init__(
        self,
        reason: str,
        *,
        retryable: bool = False,
        status: Optional[int] = None,
        request_id: Optional[str] = None,
        retry_after: Optional[float] = None,
    ):
        super().__init__(reason)  # the message is only the code, safe to log
        self.reason = reason
        self.retryable = retryable
        self.status = status
        self.request_id = request_id
        self.retry_after = retry_after

    @property
    def user_message(self) -> str:
        return WARNINGS.get(self.reason, WARNINGS["unexpected"])


def make_client(settings: Settings) -> anthropic.Anthropic:
    """Create the Anthropic client. Tests replace this one function with a fake.

    The key is passed explicitly instead of letting the SDK look for
    credentials itself. The SDK can also find credentials in other places
    (ANTHROPIC_AUTH_TOKEN, a saved login profile), which would hide the fact
    that LLM_API_KEY is missing from this server's configuration.
    """
    if not settings.anthropic_api_key:
        raise ConfigError(
            "LLM_API_KEY is not set, so the Claude extractor can't be used. "
            "Add it to backend/.env."
        )
    return anthropic.Anthropic(
        api_key=settings.anthropic_api_key,
        # Seconds. Without this the SDK waits up to 10 minutes.
        timeout=settings.llm_timeout_seconds,
        # The SDK retries twice by default. We turn that off because the
        # pipeline does its own single, visible retry (issue #22); two layers
        # of retries would multiply and blow the response-time budget.
        max_retries=0,
    )


def build_prompt(pages: List[str]) -> str:
    """Wrap each page in a numbered tag so the model can cite pages."""
    parts = [f'<page n="{i}">\n{text.strip()}\n</page>' for i, text in enumerate(pages, start=1)]
    return (
        "<protocol>\n" + "\n".join(parts) + "\n</protocol>\n\n"
        "Extract the operational plan from this protocol."
    )


def _retry_after(exc: Exception) -> Optional[float]:
    try:
        return float(exc.response.headers.get("retry-after"))  # type: ignore[attr-defined]
    except (AttributeError, TypeError, ValueError):
        return None


def map_error(exc: Exception) -> LLMError:
    """Turn an SDK exception into a reason code and a retry decision.

    Order matters: check subclasses before their parents (APITimeoutError is a
    kind of APIConnectionError; the status errors are kinds of APIStatusError).
    Retryable means "the same request might work in a moment".
    """
    status = getattr(exc, "status_code", None)
    request_id = getattr(exc, "request_id", None)
    common = {"status": status, "request_id": request_id}

    if isinstance(exc, anthropic.APITimeoutError):
        return LLMError("timeout", retryable=True)
    if isinstance(exc, anthropic.APIConnectionError):
        return LLMError("connection", retryable=True)
    if isinstance(exc, anthropic.RateLimitError):
        return LLMError("rate_limited", retryable=True, retry_after=_retry_after(exc), **common)
    if isinstance(exc, (anthropic.AuthenticationError, anthropic.PermissionDeniedError)):
        return LLMError("invalid_key", **common)
    if isinstance(exc, anthropic.APIStatusError):
        if status is not None and status >= 500:
            return LLMError("provider_error", retryable=True, retry_after=_retry_after(exc), **common)
        if status == 408:
            return LLMError("timeout", retryable=True, **common)
        return LLMError("rejected", **common)  # other 4xx: retrying won't help
    if isinstance(exc, (ValidationError, ValueError)):
        # The SDK validates the model's JSON against LLMPlan; this is what it
        # raises for malformed JSON or JSON that doesn't fit the schema.
        return LLMError("invalid_output")
    return LLMError("unexpected")


# ---------- turning model output into a validated plan ----------

def _clean(raw: dict, n_pages: int) -> dict:
    """Apply the 'never present uncertain items as certain' rules to one item."""
    item = dict(raw)
    notes = [item["notes"].strip()] if isinstance(item.get("notes"), str) and item["notes"].strip() else []

    page = item.get("source_page")
    if page is not None and not (isinstance(page, int) and 1 <= page <= n_pages):
        # A page that doesn't exist can't be checked, so drop the reference.
        item["source_page"] = None
        notes.append("The cited page doesn't exist in this PDF, so no source page is shown.")

    conf = item.get("confidence")
    if not isinstance(conf, (int, float)) or isinstance(conf, bool) or not 0 <= conf <= 1:
        item["confidence"] = 0.5
        notes.append("No usable confidence was given for this item.")
    if item.get("source_page") is None and item["confidence"] >= REVIEW_THRESHOLD:
        # No page means a reviewer can't verify it quickly: force a review.
        item["confidence"] = CAPPED
        notes.append("No source page was given; check this against the protocol.")
    elif item["confidence"] < REVIEW_THRESHOLD and not notes:
        notes.append("The model was unsure about this item.")

    item["notes"] = " ".join(notes) or None
    return item


def _build(items: List[BaseModel], model: type, n_pages: int, required: str) -> Tuple[list, int]:
    """Validate items one at a time. Returns (good items, number dropped)."""
    good, dropped = [], 0
    for raw in items:
        data = _clean(raw.model_dump(), n_pages)
        if not str(data.get(required) or "").strip():
            dropped += 1  # an item with no name is not usable
            continue
        try:
            good.append(model.model_validate(data))
        except ValidationError:
            dropped += 1
    return good, dropped


def _fix_visit_tags(items: list, known: set, label: str) -> None:
    """Remove visit ids that aren't in the schedule, and say so on the item."""
    for it in items:
        bad = [v for v in it.visits if v not in known]
        if bad:
            it.visits = [v for v in it.visits if v in known]
            note = f"Removed {label} to visit(s) not in the schedule: {', '.join(bad)}."
            it.notes = f"{it.notes} {note}" if it.notes else note
            it.confidence = min(it.confidence if it.confidence is not None else CAPPED, CAPPED)


def to_plan(llm: LLMPlan, parsed: ParsedDocument, model_name: str) -> OperationalPlan:
    """Convert the model's output into the strict plan, flagging what's doubtful."""
    n = len(parsed.pages)
    reasons: dict = {}

    def flag(section: str, reason: str) -> None:
        reasons.setdefault(section, []).append(reason)

    def section(key: str, items, model, required) -> list:
        good, dropped = _build(items, model, n, required)
        if dropped:
            flag(key, f"{dropped} item(s) from the AI model were invalid and were left out.")
        return good

    visits = section("visits", llm.visits, Visit, "id")
    seen, unique = set(), []
    for v in visits:
        if v.id in seen:  # ids must be unique for procedures to reference them
            flag("visits", f"Two visits shared the id {v.id}; the second was left out.")
            continue
        seen.add(v.id)
        unique.append(v)
    visits = unique

    procedures = section("procedures", llm.procedures, Procedure, "name")
    staffing = section("staffing", llm.staffing, StaffingRole, "role")
    safety = section("safety", llm.safety, SafetyReport, "event")
    billing = section("billing", llm.billing, BillingItem, "item")
    equipment = section("equipment", llm.equipment, EquipmentItem, "item")
    pharmacy_items = section("pharmacy", llm.pharmacy_items, PharmacyItem, "item")
    technology = section("technology", llm.technology, TechnologyItem, "system")

    _fix_visit_tags(procedures, seen, "links")
    _fix_visit_tags(billing, seen, "links")

    # Visits can't be reviewed one by one in the UI, so low-confidence visits
    # flag the whole section instead.
    unsure = [v.id for v in visits if v.confidence is not None and v.confidence < REVIEW_THRESHOLD]
    if unsure:
        flag("visits", f"Check these visits against the schedule of activities: {', '.join(unsure)}.")

    found = {"visits": visits, "procedures": procedures, "staffing": staffing}
    for key in CORE_SECTIONS:
        if not found[key]:
            flag(key, f"No {key} were found in the protocol text. Check the protocol and add them manually.")

    # pharmacy stays None when the model couldn't tell, so the UI says
    # "no pharmacy info" instead of claiming pharmacy is not involved.
    pharmacy = None
    if llm.pharmacy_involved is not None or pharmacy_items:
        pharmacy = Pharmacy(involved=bool(llm.pharmacy_involved) or bool(pharmacy_items), items=pharmacy_items)

    h = llm.protocol
    # The registry id and page count come from the PDF itself, not the model:
    # they are exact facts we can read deterministically.
    registry_id = find_registry_id(parsed.pages, parsed.filename)
    enrollment = h.enrollment if isinstance(h.enrollment, int) and h.enrollment >= 0 else None

    return OperationalPlan(
        id=registry_id or parsed.filename,
        is_sample=False,
        extraction="llm",
        protocol=ProtocolMetadata(
            title=h.title,
            short_title=h.short_title,
            registry_id=registry_id,
            protocol_number=h.protocol_number,
            phase=h.phase,
            sponsor=h.sponsor,
            therapeutic_area=h.therapeutic_area,
            design=h.design,
            enrollment=enrollment,
            duration=h.duration,
            pages=n,
        ),
        visits=visits,
        procedures=procedures,
        staffing=staffing,
        safety=safety,
        billing=billing,
        equipment=equipment,
        pharmacy=pharmacy,
        technology=technology,
        section_reviews=SectionReviews(
            **{k: ReviewFlag(needs_review=True, reason=" ".join(v)) for k, v in reasons.items()}
        ),
    )


class ClaudeExtractor:
    """Extracts a plan by sending the whole protocol to Claude in one request.

    Why the whole document and not chunks: a 150-page protocol is roughly
    75-120K tokens and the model's context window is 1M, so it fits. The
    schedule-of-activities table refers to visits defined elsewhere, and
    splitting the text would separate them and need a second merging step.
    """

    name = "llm"

    def __init__(self, settings: Settings, clock: Callable[[], float] = time.monotonic):
        self.model = settings.llm_model
        self.effort = settings.llm_effort
        self.timeout = settings.llm_timeout_seconds
        self.client = make_client(settings)
        self._clock = clock

    def extract(self, parsed: ParsedDocument, *, deadline: Optional[float] = None) -> OperationalPlan:
        """Raises LLMError (with a reason code) if the model can't be used."""
        prompt = build_prompt(parsed.pages)
        if len(prompt) > MAX_INPUT_CHARS:
            raise LLMError("too_long")

        # Never wait past the request's overall deadline.
        timeout = self.timeout
        if deadline is not None:
            remaining = deadline - self._clock()
            if remaining < 5:
                raise LLMError("deadline")
            timeout = min(timeout, remaining)

        try:
            response = self.client.with_options(timeout=timeout).messages.parse(
                model=self.model,
                max_tokens=MAX_OUTPUT_TOKENS,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": prompt}],
                # Structured output: the API constrains the reply to this
                # schema and the SDK parses it into an LLMPlan.
                output_format=LLMPlan,
                output_config={"effort": self.effort},
            )
        except LLMError:
            raise
        except Exception as exc:  # mapped to a safe reason; details are not kept
            raise map_error(exc) from None

        stop = getattr(response, "stop_reason", None)
        if stop == "refusal":
            raise LLMError("refused")
        if stop == "max_tokens":
            raise LLMError("truncated")

        llm_plan = _parsed_output(response)
        if not isinstance(llm_plan, LLMPlan):
            raise LLMError("invalid_output")
        try:
            return to_plan(llm_plan, parsed, self.model)
        except ValidationError:
            raise LLMError("invalid_output") from None


def _parsed_output(response: Any) -> Any:
    """The parsed LLMPlan from the first text block of the response."""
    for block in getattr(response, "content", None) or []:
        if getattr(block, "type", None) == "text":
            return getattr(block, "parsed_output", None)
    return None
