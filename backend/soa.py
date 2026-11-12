"""Reads the Schedule of Activities (SoA) table for keyword extraction.

No AI here either. PyMuPDF's table finder locates ruled tables on pages that
mention a schedule. The header rows become visits (one per column), the body
rows become procedures, and a mark (X, ✓, •) in a visit column tags that
visit. Anything that is not a recognized mark, such as "Q16W" or
"continually", is kept as an unrecognized entry for a reviewer instead of
being guessed at.

Known limits, which the plan flags rather than hides:
- A schedule laid out without table lines, or scanned as a picture, isn't
  found, and the plan says so.
- Visits are matched across tables by their column heading, so two parts of a
  study that both have a "Day 1" share one visit.
"""

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import pymupdf

# Page text that suggests a schedule table is on the page.
SOA_TITLE = re.compile(
    r"schedule of (activities|assessments|events|procedures|evaluations|study (procedures|assessments))"
    r"|time and events|study (flow ?chart|calendar)|\bflow ?chart\b",
    re.I,
)
# Table detection is slow (about 50 ms a page), so it runs on at most this many pages.
MAX_SOA_PAGES = 30

# Symbol and Wingdings fonts put ± and check marks at private-use code points.
SYMBOLS = {"": "±", "": "+", "": "-", "": "•", "": "●", "": "✓", "": "√"}

# A cell that is only a mark, optionally in brackets (conditional) or with a footnote sign.
# "·" is how many PDFs extract a bullet drawn in the Symbol font.
MARK = re.compile(r"^([(\[])?\s*(x|✓|✔|√|•|·|∙|●|■|◆|yes)\s*[)\]]?\s*[*†‡§¶#]*$", re.I)
# Column headings that are not visits.
NOT_A_VISIT = re.compile(r"^(notes?|comments?|remarks?|footnotes?|details?|(protocol )?sections?|ref(erence)?s?\.?)$", re.I)
# The heading of the procedure column, which ends the header rows.
LABEL_HEAD = re.compile(r"^(study )?(procedures?|assessments?|activit(y|ies)|evaluations?|tests?)\b", re.I)
VISIT_LIKE = re.compile(
    r"screen|\bscr\b|baseline|randomi|\bday\b|\bweek|\bwk\b|\bmonth|\byear|visit|\bv\d|follow|\bf/?u\b|\beo[st]\b"
    r"|end of|cycle|\bc\d+|terminat|discontinu|unscheduled|enrol|\bet\b|final|phone|call|treatment|period",
    re.I,
)
WINDOW = re.compile(r"(±|\+\s*/\s*[-−–])\s*(\d+(?:\.\d+)?)\s*(days?|d\b|weeks?|wks?|hours?|hrs?|h\b)?", re.I)
DAY = re.compile(r"\b(day|week|month|year)\s*(-?\d+)(?:\s*(?:to|through|-|–)\s*(?:day\s*)?(-?\d+))?", re.I)
UNITS = {"d": "days", "day": "days", "wk": "weeks", "wks": "weeks", "week": "weeks", "h": "hours", "hr": "hours", "hrs": "hours", "hour": "hours"}


def clean(text: str) -> str:
    for code, char in SYMBOLS.items():
        text = text.replace(code, char)
    return re.sub(r"\s+", " ", text).strip()


def mark(text: str) -> Optional[str]:
    """"x" for a plain mark, "conditional" for a bracketed one like (X), else None."""
    m = MARK.match(clean(text))
    if not m:
        return None
    return "conditional" if m.group(1) else "x"


def window(text: str) -> Optional[str]:
    m = WINDOW.search(clean(text))
    if not m:
        return None
    unit = (m.group(3) or "").lower()
    unit = UNITS.get(unit, unit)
    return f"±{m.group(2)} {unit}".strip()


def day(text: str) -> Optional[str]:
    m = DAY.search(clean(text))
    if not m:
        return None
    out = f"{m.group(1).capitalize()} {m.group(2)}"
    return f"{out} to {m.group(3)}" if m.group(3) else out


# ---------- reading one table ----------

@dataclass
class Cell:
    text: str
    first: int  # first and last column the cell covers
    last: int


def _page_lines(page, flags):
    """Text lines on the page as (bbox, [(span bbox, text)]), without superscripts.

    Superscripts are footnote markers ("SCRᵃ"). Dropping them keeps them out
    of visit and procedure names.
    """
    d = page.get_text("dict", flags=pymupdf.TEXTFLAGS_DICT & ~pymupdf.TEXT_PRESERVE_IMAGES | flags)
    lines = []
    for b in d["blocks"]:
        for line in b.get("lines", []):
            spans = [(pymupdf.Rect(s["bbox"]), s["text"]) for s in line["spans"] if not s["flags"] & 1]
            if spans:
                lines.append(spans)
    return lines


def _cell_text(rect, lines) -> str:
    parts = []
    for spans in lines:
        text = "".join(t for r, t in spans if rect.contains((r.tl + r.br) / 2))
        if text.strip():
            parts.append(text.strip())
    out = ""
    for p in parts:
        # Rejoin words hyphenated across lines ("Follow-" + "Up").
        out = out + p if out.endswith("-") else f"{out} {p}"
    return clean(out)


def _grid(table, lines) -> List[List[Optional[Cell]]]:
    """The table as rows of cells. A cell spanning columns appears in each of
    them; a position covered from the row above is None."""
    ncols = table.col_count
    left = [min((r.cells[c][0] for r in table.rows if r.cells[c]), default=None) for c in range(ncols)]
    grid = []
    for row in table.rows:
        out: List[Optional[Cell]] = [None] * ncols
        for c, bbox in enumerate(row.cells):
            if bbox is None or out[c] is not None:
                continue
            last = c
            while last + 1 < ncols and left[last + 1] is not None and left[last + 1] < bbox[2] - 1:
                last += 1
            cell = Cell(_cell_text(pymupdf.Rect(bbox), lines), c, last)
            for k in range(c, last + 1):
                out[k] = cell
        grid.append(out)
    return grid


def _text(cell: Optional[Cell]) -> str:
    return cell.text if cell else ""


def _is_heading(row) -> bool:
    """A section label across the row, like "Laboratory Assessments"."""
    return bool(_text(row[0])) and all(c is None or c is row[0] or not c.text for c in row[1:])


def _header_size(grid) -> int:
    """How many rows at the top are column headings.

    The header ends at the first row with a mark, the first section label, or
    the first labelled row after the "Procedure" heading (which may sit at the
    top or the bottom of the header).
    """
    labelled = False
    for r, row in enumerate(grid):
        first = _text(row[0])
        if any(mark(_text(c)) for c in row[1:] if c and c.first > 0):
            return r
        if r > 0 and _is_heading(row):
            return r
        if labelled and first:
            return r
        labelled = labelled or bool(LABEL_HEAD.match(first))
    return len(grid)


@dataclass
class Column:
    name: str
    day: Optional[str]
    window: Optional[str]
    group: Optional[str]  # a heading over several columns, like "Treatment Period"


def _columns(header) -> Dict[int, Column]:
    """Visit columns by index, from the header rows."""
    if not header:
        return {}
    ncols = len(header[0])
    cols = {}
    for c in range(1, ncols):
        own, group, windows = [], [], []
        for row in header:
            cell = row[c]
            if not cell or not cell.text or cell.first == 0:
                continue  # empty, or a title running across from the label column
            if re.search(r"\bwindow\b", cell.text, re.I):
                windows.append(cell.text)
            elif cell.last > cell.first:
                group.append(cell.text)
            else:
                own.append(cell.text)
        name = " ".join(own) or " ".join(group)
        if not name or NOT_A_VISIT.match(name):
            continue
        if own and group and not re.search(r"[A-Za-z]", re.sub(r"\(.*?\)", "", name)):
            # A bare number like "1 (week 48)" under "Treatment Period (years)".
            name = f"{group[-1]} {name}"
        context = " ".join(group) if own and group else None
        cols[c] = Column(
            name=name[0].upper() + name[1:],
            day=day(name),
            window=next(filter(None, map(window, own + windows + group)), None),
            group=context,
        )
    return cols


# ---------- the whole schedule ----------

@dataclass
class Row:
    name: str
    section: Optional[str]
    page: int
    visits: List[str] = field(default_factory=list)       # visit ids, in schedule order
    conditional: List[str] = field(default_factory=list)  # ids marked "(X)"
    unknown: Dict[str, List[str]] = field(default_factory=dict)  # entry text -> visit names


@dataclass
class Schedule:
    visits: List[dict]
    rows: List[Row]
    pages: List[int]

    @property
    def unknown_entries(self) -> List[str]:
        return [text for row in self.rows for text in row.unknown]


def _key(text: str) -> str:
    return re.sub(r"[^a-z0-9±+-]+", " ", text.lower()).strip()


class _Reader:
    def __init__(self):
        self.visits: Dict[str, dict] = {}  # visit key -> visit
        self.rows: Dict[str, Row] = {}     # row key -> row
        self.pages: List[int] = []
        self.last_columns: Optional[Tuple[int, Dict[int, str]]] = None  # (ncols, column -> visit id)

    def _visit(self, col: Column, page: int) -> str:
        key = _key(col.name)
        if key not in self.visits:
            visit_like = bool(VISIT_LIKE.search(col.name))
            notes = f"Column of the schedule table on page {page}."
            if col.group:
                notes += f" Under \"{col.group}\"."
            if not visit_like:
                notes += " The heading doesn't look like a visit name; check it."
            self.visits[key] = {
                "id": f"V{len(self.visits) + 1}",
                "name": col.name,
                "day": col.day,
                "window": col.window,
                "type": "Phone" if re.search(r"phone|\bcall\b", col.name, re.I) else None,
                "notes": notes,
                "source_page": page,
                "confidence": 0.8 if visit_like else 0.55,
            }
        return self.visits[key]["id"]

    def read_table(self, grid, page: int, titled: bool) -> bool:
        """Add one table to the schedule. False if it isn't a schedule."""
        if not grid or len(grid[0]) < 3:
            return False
        ncols = len(grid[0])
        h = _header_size(grid)
        columns = _columns(grid[:h])
        # A continuation needs only one marked row: the columns already passed as a schedule.
        continued = bool(columns) and all(_key(c.name) in self.visits for c in columns.values())
        if not columns and self.last_columns and self.last_columns[0] == ncols:
            # A continuation without its own header: same columns as before.
            ids = self.last_columns[1]
            continued = True
        else:
            visit_like = sum(bool(VISIT_LIKE.search(c.name)) for c in columns.values())
            if len(columns) < 2 or not (titled or visit_like >= 2):
                return False
            ids = None
        body = grid[h:]
        marked = sum(any(mark(_text(row[c])) for c in range(1, ncols)) for row in body)
        if marked < (1 if continued else 2):
            return False

        if ids is None:
            ids = {c: self._visit(col, page) for c, col in columns.items()}
        self.last_columns = (ncols, ids)
        names = {v["id"]: v["name"] for v in self.visits.values()}
        section = None
        for row in body:
            label = _text(row[0])
            if not label or (row[0] and row[0].first > 0):
                continue
            if _is_heading(row):
                section = re.sub(r"[\s(]*(continued|cont'?d|cont\.)\)?$", "", label, flags=re.I)
                continue
            entry = self.rows.setdefault(_key(label), Row(name=label, section=section, page=page))
            for c, vid in ids.items():
                cell = row[c]
                if not cell or not cell.text or cell.first == 0:
                    continue
                kind = mark(cell.text)
                if kind:
                    if vid not in entry.visits:
                        entry.visits.append(vid)
                    if kind == "conditional" and vid not in entry.conditional:
                        entry.conditional.append(vid)
                else:
                    seen = entry.unknown.setdefault(cell.text, [])
                    if names[vid] not in seen:
                        seen.append(names[vid])
        if page not in self.pages:
            self.pages.append(page)
        return True

    def result(self) -> Optional[Schedule]:
        if not self.visits:
            return None
        order = {v["id"]: i for i, v in enumerate(self.visits.values())}
        for row in self.rows.values():
            row.visits.sort(key=order.get)
        return Schedule(visits=list(self.visits.values()), rows=list(self.rows.values()), pages=self.pages)


def _marks(text: str) -> int:
    # Cheap check before the slow table finder: schedule cells holding only a
    # mark come out of the text layer as lines of their own.
    return sum(bool(mark(line)) for line in text.splitlines() if len(line) < 8)


def read_schedule(doc, pages: List[str], skip, flags: int = 0) -> Optional[Schedule]:
    """Find and read the schedule table(s). None if no schedule table is found.

    Looks at pages that mention a schedule, and at the page after each page
    where a schedule table was read (for tables continued without a title).
    """
    titled = {i for i, t in enumerate(pages) if SOA_TITLE.search(t)}
    todo = sorted(titled)
    reader = _Reader()
    done, found_on = set(), set()
    while todo and len(done) < MAX_SOA_PAGES:
        i = todo.pop(0)
        # A page that continues a schedule may hold only a row or two.
        if i in done or i in skip or i >= doc.page_count or _marks(pages[i]) < (1 if i - 1 in found_on else 3):
            continue
        done.add(i)
        page = doc[i]
        try:
            tables = page.find_tables().tables
        except Exception:
            continue  # table detection is best-effort; the plan flags a missing schedule
        if not tables:
            continue
        lines = _page_lines(page, flags)
        found = False
        for table in tables:
            found |= reader.read_table(_grid(table, lines), i + 1, i in titled)
        if found:
            found_on.add(i)
            if i + 1 not in done and i + 1 not in todo:
                todo = sorted(todo + [i + 1])
    return reader.result()
