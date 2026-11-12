"""Accuracy evaluation for CORA's extractors (issue #35).

Runs every protocol in the test set (tests/fixtures/protocols/<NCT>/) through
the real API, in-process with FastAPI's TestClient, once per extractor, and
compares each plan with the hand-checked answer file (expected.json).

    python eval.py                      # keyword extractor only (free, offline)
    python eval.py --live               # also the Claude extractor (needs LLM_API_KEY, costs money)
    python eval.py --allow-draft        # print results even for unverified answer files (labeled)
    python eval.py --protocols-dir DIR  # use another test set

Nothing here re-implements extraction: the upload goes through POST
/api/protocols, which is the full pipeline (ingest, OCR, extraction, merge,
validation). The extractor is switched with EXTRACTOR, the same setting
the server uses. DATABASE_URL is ignored, so nothing is stored or reused.

Metric
------
For each of the eight categories (visits, procedures, staffing, safety,
billing, equipment, pharmacy, technology):

1. Names are normalized: lowercased, punctuation removed, whitespace
   collapsed, a trailing plural "s" dropped from words longer than three
   letters, and a small synonym list applied (SYNONYMS below), so
   "Electrocardiogram (ECG)" and "ECGs" compare equal.
2. Two names match when the token overlap (Jaccard: shared words / all words)
   is at least MATCH_THRESHOLD. Pairs are taken best score first and each
   item matches at most one item on the other side.
3. precision = matched / extracted, recall = matched / expected. When a side
   is empty the value is undefined and shown as "n/a" (0/0 is not 100%).

Procedure-to-visit mapping is scored separately: visits are aligned first
(from the visit matches in step 2), then every (procedure, visit) pair in the
answer file is a hit when the matched extracted procedure lists the aligned
extracted visit. Precision is over all (procedure, visit) pairs the extractor
produced.

Unverified answer files (status starting with DRAFT, or no verified_by /
verified_on) are never reported as results. The script refuses to print a
table for them unless --allow-draft is passed, and then every row is labeled.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterator, List, Optional, Sequence, Tuple

import pymupdf
from pydantic import BaseModel, ConfigDict

DEFAULT_DIR = Path(__file__).parent / "tests" / "fixtures" / "protocols"
MATCH_THRESHOLD = 0.5
DRAFT_LABEL = "UNVERIFIED DRAFT, NOT A RESULT"
# Rough Opus 5.5 cost per page from PLAN.md (#18): ~$0.45-0.60 per 100 pages,
# rounded up so the estimate errs high.
COST_PER_PAGE_USD = 0.006

CATEGORIES = ("visits", "procedures", "staffing", "safety", "billing", "equipment", "pharmacy", "technology")
# Which field holds the item's name, per category (field names follow models.py).
NAME_FIELD = {
    "visits": "name", "procedures": "name", "staffing": "role", "safety": "event",
    "billing": "item", "equipment": "item", "pharmacy": "item", "technology": "system",
}
# Phrase -> canonical form, applied to normalized text. Keep it small and
# obvious; a long list would hide real extraction misses.
SYNONYMS = {
    "electrocardiogram": "ecg",
    "ekg": "ecg",
    "12 lead ecg": "ecg",
    "informed consent form": "informed consent",
    "icf": "informed consent",
    "physical examination": "physical exam",
    "pi": "principal investigator",
    "study coordinator": "clinical research coordinator",
    "crc": "clinical research coordinator",
    "sae": "serious adverse event",
    "edc": "electronic data capture",
    "blood sample": "blood draw",
    "blood collection": "blood draw",
    "vital sign": "vital",  # "Vitals" becomes "vital" after the plural step
}


# ---------- answer file ----------

class _Item(BaseModel):
    model_config = ConfigDict(extra="ignore")


class ExpectedVisit(_Item):
    id: str
    name: Optional[str] = None


class ExpectedProcedure(_Item):
    name: str
    visits: List[str] = []


class ExpectedStaff(_Item):
    role: str


class ExpectedSafety(_Item):
    event: str


class ExpectedThing(_Item):
    item: str


class ExpectedSystem(_Item):
    system: str


class Expected(BaseModel):
    """One protocol's answer file. Every category is required (may be empty)."""

    status: str
    verified_by: Optional[str] = None
    verified_on: Optional[str] = None
    nct_id: Optional[str] = None
    source_url: Optional[str] = None
    visits: List[ExpectedVisit]
    procedures: List[ExpectedProcedure]
    staffing: List[ExpectedStaff]
    safety: List[ExpectedSafety]
    billing: List[ExpectedThing]
    equipment: List[ExpectedThing]
    pharmacy: List[ExpectedThing]
    technology: List[ExpectedSystem]

    @property
    def verified(self) -> bool:
        return bool(
            self.verified_by and self.verified_on and not self.status.strip().upper().startswith("DRAFT")
        )


# ---------- scoring ----------

def normalize(name: Optional[str]) -> str:
    text = re.sub(r"[^\w\s]", " ", (name or "").lower())
    words = [w[:-1] if len(w) > 3 and w.endswith("s") and not w.endswith("ss") else w for w in text.split()]
    text = " ".join(words)
    for phrase in sorted(SYNONYMS, key=len, reverse=True):
        text = re.sub(rf"\b{re.escape(phrase)}\b", SYNONYMS[phrase], text)
    return " ".join(text.split())


def similarity(a: str, b: str) -> float:
    ta, tb = set(normalize(a).split()), set(normalize(b).split())
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def match(expected: Sequence[str], extracted: Sequence[str], threshold: float = MATCH_THRESHOLD) -> Dict[int, int]:
    """One-to-one matching, best score first. Returns {expected index: extracted index}."""
    candidates = sorted(
        ((similarity(e, x), i, j) for i, e in enumerate(expected) for j, x in enumerate(extracted)),
        key=lambda c: (-c[0], c[1], c[2]),
    )
    pairs: Dict[int, int] = {}
    used = set()
    for score, i, j in candidates:
        if score < threshold:
            break
        if i not in pairs and j not in used:
            pairs[i] = j
            used.add(j)
    return pairs


@dataclass
class Score:
    expected: int
    extracted: int
    matched: int

    @property
    def precision(self) -> Optional[float]:
        return self.matched / self.extracted if self.extracted else None

    @property
    def recall(self) -> Optional[float]:
        return self.matched / self.expected if self.expected else None


def _extracted_items(plan: dict, category: str) -> List[dict]:
    if category == "pharmacy":
        return list((plan.get("pharmacy") or {}).get("items") or [])
    return list(plan.get(category) or [])


def _names(items: List[dict], category: str) -> List[str]:
    key = NAME_FIELD[category]
    if category == "visits":
        return [i.get("name") or i.get("id") or "" for i in items]
    return [i.get(key) or "" for i in items]


def score_plan(expected: Expected, plan: dict) -> Dict[str, Score]:
    """Score one extracted plan (the API's JSON) against one answer file."""
    scores: Dict[str, Score] = {}
    matches: Dict[str, Dict[int, int]] = {}
    for category in CATEGORIES:
        exp_items = [i.model_dump() for i in getattr(expected, category)]
        ext_items = _extracted_items(plan, category)
        m = match(_names(exp_items, category), _names(ext_items, category))
        matches[category] = m
        scores[category] = Score(len(exp_items), len(ext_items), len(m))
    scores["procedure→visit"] = score_visit_pairs(expected, plan, matches["visits"], matches["procedures"])
    return scores


def score_visit_pairs(expected: Expected, plan: dict, visit_match: Dict[int, int], proc_match: Dict[int, int]) -> Score:
    ext_visits = plan.get("visits") or []
    ext_procs = plan.get("procedures") or []
    visit_id = {expected.visits[i].id: ext_visits[j].get("id") for i, j in visit_match.items()}
    exp_pairs = [(i, v) for i, p in enumerate(expected.procedures) for v in p.visits]
    hits = 0
    for i, v in exp_pairs:
        j = proc_match.get(i)
        if j is not None and visit_id.get(v) is not None and visit_id[v] in (ext_procs[j].get("visits") or []):
            hits += 1
    n_extracted = sum(len(p.get("visits") or []) for p in ext_procs)
    return Score(len(exp_pairs), n_extracted, hits)


# ---------- running the API ----------

@dataclass
class Protocol:
    name: str
    pdf: Path
    expected: Expected


@dataclass
class Run:
    plan: Optional[dict] = None
    error: Optional[str] = None
    fallback: bool = False
    scores: Dict[str, Score] = field(default_factory=dict)


def load_protocols(directory: Path) -> List[Protocol]:
    protocols = []
    if not directory.is_dir():
        return protocols
    for sub in sorted(p for p in directory.iterdir() if p.is_dir()):
        pdf, answer = sub / "protocol.pdf", sub / "expected.json"
        if pdf.is_file() and answer.is_file():
            protocols.append(Protocol(sub.name, pdf, Expected.model_validate_json(answer.read_text())))
    return protocols


@contextmanager
def _env(**values: Optional[str]) -> Iterator[None]:
    old = {k: os.environ.get(k) for k in values}
    for k, v in values.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v
    try:
        yield
    finally:
        for k, v in old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def run_extractor(protocol: Protocol, extractor: str) -> Run:
    """Upload one protocol through POST /api/protocols with the named extractor."""
    from fastapi.testclient import TestClient

    import main  # imported here so main's load_dotenv runs before we override settings

    # DATABASE_URL="" counts as unset, so the run never reads or writes saved plans.
    with _env(EXTRACTOR=extractor, DATABASE_URL=""):
        client = TestClient(main.app)
        r = client.post(
            "/api/protocols",
            files={"file": (protocol.pdf.name, protocol.pdf.read_bytes(), "application/pdf")},
        )
    if r.status_code != 200:
        detail = r.json().get("detail") if r.headers.get("content-type", "").startswith("application/json") else r.text
        return Run(error=f"HTTP {r.status_code}: {str(detail)[:120]}")
    plan = r.json()
    info = plan.get("extraction_info") or {}
    return Run(plan=plan, fallback=bool(info.get("fallback")), scores=score_plan(protocol.expected, plan))


# ---------- output ----------

def _pct(value: Optional[float]) -> str:
    return "n/a" if value is None else f"{value * 100:.0f}%"


def _pr(score: Optional[Score]) -> str:
    if score is None:
        return "not run"
    return f"{_pct(score.precision)} / {_pct(score.recall)}"


def _table(rows: List[List[str]]) -> str:
    widths = [max(len(r[c]) for r in rows) for c in range(len(rows[0]))]
    lines = ["  ".join(cell.ljust(w) for cell, w in zip(row, widths)).rstrip() for row in rows]
    lines.insert(1, "  ".join("-" * w for w in widths))
    return "\n".join(lines)


def _run_cell(run: Optional[Run], category: str) -> str:
    if run is None:
        return "not run"
    if run.error:
        return "error"
    return _pr(run.scores.get(category))


def report(protocol: Protocol, keyword: Run, llm: Optional[Run]) -> str:
    draft = not protocol.expected.verified
    header = ["category", "expected", "keyword P / R", "LLM P / R"] + (["label"] if draft else [])
    rows = [header]
    for category in (*CATEGORIES, "procedure→visit"):
        if category in CATEGORIES:
            expected_n = len(getattr(protocol.expected, category))
        else:
            expected_n = sum(len(p.visits) for p in protocol.expected.procedures)
        row = [category, str(expected_n), _run_cell(keyword, category), _run_cell(llm, category)]
        rows.append(row + ([DRAFT_LABEL] if draft else []))
    title = f"{protocol.name} ({protocol.expected.nct_id or 'no NCT id'})" + (f"  [{DRAFT_LABEL}]" if draft else "")
    notes = []
    for label, run in (("keyword", keyword), ("LLM", llm)):
        if run and run.error:
            notes.append(f"{label} run failed: {run.error}")
        if run and run.fallback:
            notes.append(f"{label} run fell back to keyword extraction ({(run.plan or {}).get('extraction_info', {}).get('reason')})")
    return "\n".join([title, _table(rows), *notes])


def summary(results: List[Tuple[Protocol, Run, Optional[Run]]]) -> str:
    """Mean precision and recall per category across protocols (n/a values skipped)."""
    def mean(values: List[Optional[float]]) -> Optional[float]:
        values = [v for v in values if v is not None]
        return sum(values) / len(values) if values else None

    any_draft = any(not p.expected.verified for p, _, _ in results)
    rows = [["category", "keyword P / R (mean)", "LLM P / R (mean)"] + (["label"] if any_draft else [])]
    for category in (*CATEGORIES, "procedure→visit"):
        cells = [category]
        for which in (1, 2):
            runs = [r[which] for r in results if r[which] is not None and not r[which].error]
            if not runs:
                cells.append("not run")
                continue
            s = [run.scores[category] for run in runs]
            cells.append(f"{_pct(mean([x.precision for x in s]))} / {_pct(mean([x.recall for x in s]))}")
        rows.append(cells + ([DRAFT_LABEL] if any_draft else []))
    return f"Overall, mean of {len(results)} protocol(s)\n" + _table(rows)


# ---------- command line ----------

def _page_count(pdf: Path) -> int:
    with pymupdf.open(pdf) as doc:
        return doc.page_count


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Score CORA's extractors against the hand-checked protocol test set.")
    parser.add_argument("--protocols-dir", type=Path, default=DEFAULT_DIR)
    parser.add_argument("--live", action="store_true", help="also run the Claude extractor (real API calls, costs money)")
    parser.add_argument("--allow-draft", action="store_true", help="print results for unverified answer files, labeled")
    args = parser.parse_args(argv)

    protocols = load_protocols(args.protocols_dir)
    if not protocols:
        print(f"No protocols in {args.protocols_dir}; see its README for the layout.")
        return 0

    drafts = [p.name for p in protocols if not p.expected.verified]
    if drafts and not args.allow_draft:
        print(
            "These answer files are unverified drafts, so no results are printed: "
            + ", ".join(drafts)
            + ".\nVerify each against its PDF and set verified_by and verified_on, "
            "or pass --allow-draft to see labeled, unofficial numbers."
        )
        return 1

    if args.live:
        if not os.environ.get("LLM_API_KEY"):
            # main.py loads backend/.env on import; do the same before checking.
            import main as _app  # noqa: F401
        if not os.environ.get("LLM_API_KEY"):
            print("--live needs LLM_API_KEY (in the environment or backend/.env).")
            return 2
        pages = sum(_page_count(p.pdf) for p in protocols)
        estimate = pages * COST_PER_PAGE_USD
        answer = input(
            f"--live sends {len(protocols)} protocol(s), {pages} pages, to the Claude API. "
            f"Estimated cost: about ${estimate:.2f} (one retry could double a request). Continue? [y/N] "
        )
        if answer.strip().lower() not in ("y", "yes"):
            print("Cancelled; nothing was sent.")
            return 1

    results = []
    for protocol in protocols:
        keyword = run_extractor(protocol, "keyword")
        llm = run_extractor(protocol, "llm") if args.live else None
        results.append((protocol, keyword, llm))
        print(report(protocol, keyword, llm))
        print()
    print(summary(results))
    if not args.live:
        print("\nLLM column: not run. Pass --live to include the Claude extractor.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
