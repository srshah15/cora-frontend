"""Pick the pages of a long protocol that are worth sending to the LLM.

Why: a 120-page protocol is ~100K input tokens. On the cheapest model that is
slow, and the model either gives up (an empty plan) or runs out of output room
before the plan is finished. Most of those pages are background, statistics
and references. The operational content sits in a few places: the title page
and synopsis, the schedule of activities, and the sections on procedures,
safety reporting, the investigational product, staff and payments.

How: every page gets a score from cheap text signals (headings, table-like
pages full of X marks, and the keyword patterns the keyword extractor already
uses). The first pages and the schedule-of-activities pages (with a neighbour
on each side, since the table runs across pages) are always kept. The rest are
filled with the highest-scoring pages up to the limit. Pages keep their
original numbers, so the model's source_page citations still point at the PDF.
"""

from __future__ import annotations

import re
from typing import List

from extract import EQUIPMENT, PHARMACY, PROCEDURES, SAFETY, STAFFING, TECHNOLOGY, _flat, _is_toc

# Protocols up to this many pages are sent whole. 50 pages is roughly 40K
# input tokens: under half of a typical 120-page protocol.
MAX_LLM_PAGES = 50
# Title page and synopsis.
ALWAYS_FIRST = 3

SCHEDULE = re.compile(r"schedule of (activities|assessments|events|study (procedures|visits))|time and events|study flow ?chart", re.I)
# A table page: many cells that are just a mark.
TABLE_MARK = re.compile(r"^\s*(?:x|\(x\)|\[x\]|✓|✔|•)\s*$", re.I | re.M)
HEADINGS = re.compile(
    r"synopsis|study design|study procedures|study assessments|visit (schedule|window)s?"
    r"|(adverse|serious adverse) events? (reporting|definitions?)|reporting (of )?(serious )?adverse|safety reporting"
    r"|investigational (medicinal )?product|study (drug|treatment|intervention)s? (administration|storage|handling|supply|accountability)"
    r"|storage (and|&) handling|drug accountability|pharmacy"
    r"|study (staff|personnel|team)|responsibilit(y|ies) of the investigator|investigator responsibilit"
    r"|qualifications?|training requirements?"
    r"|compensation|payments? to (participants|subjects)|cost to (participants|subjects)|billing|reimbursement"
    r"|equipment|supplies|electronic data capture|\bedc\b|\birt\b|\biwrs\b|\bepro\b",
    re.I,
)
# Reporting obligations: a deadline, or who must be told. These pages hold the
# safety timelines, which are easy to miss because they rarely have headings.
REPORTING = re.compile(
    r"within (\d+|one|two|three|five|seven|ten|fifteen|twenty-four|twenty four) (calendar |business |working )?(hours?|days?)"
    r"|(inform|notify|report (it |this |them )?to) (the )?(sponsor|irb|iec|ethics committee|medical monitor)"
    r"|reporting period|expedited report|pregnanc",
    re.I,
)
KEYWORDS = [re.compile(row[-1], re.I) for row in (*PROCEDURES, *EQUIPMENT, *TECHNOLOGY, *PHARMACY, *SAFETY, *STAFFING)]


def _score(text: str) -> float:
    flat = _flat(text)
    score = 0.0
    if SCHEDULE.search(flat):
        score += 20
    marks = len(TABLE_MARK.findall(text))
    if marks >= 10:
        score += 10 + min(marks, 60) / 6
    score += 3 * min(len(HEADINGS.findall(flat)), 5)
    score += 5 * min(len(REPORTING.findall(flat)), 3)
    score += min(sum(1 for rx in KEYWORDS if rx.search(flat)), 15)
    return score


def select_pages(pages: List[str], max_pages: int = MAX_LLM_PAGES) -> List[int]:
    """0-based indexes of the pages to send, in document order."""
    n = len(pages)
    if n <= max_pages:
        return list(range(n))

    toc = {i for i, t in enumerate(pages) if _is_toc(t)}
    keep = set(range(min(ALWAYS_FIRST, n)))
    for i, text in enumerate(pages):
        if i in toc:
            continue
        flat = _flat(text)
        is_table = len(TABLE_MARK.findall(text)) >= 10
        if SCHEDULE.search(flat) and is_table:
            # The schedule table itself, plus its continuation pages.
            keep.update(j for j in (i - 1, i, i + 1) if 0 <= j < n and j not in toc)

    scores = {i: _score(t) for i, t in enumerate(pages) if i not in toc and i not in keep}
    for i in sorted(scores, key=lambda i: (-scores[i], i)):
        if len(keep) >= max_pages:
            break
        if scores[i] > 0:
            keep.add(i)
    return sorted(keep)[:max_pages] if len(keep) > max_pages else sorted(keep)
