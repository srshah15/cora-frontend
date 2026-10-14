"""Rule-based extraction of an operational plan from protocol PDF text.

No AI here: this reads the PDF's text layer, pulls the study header from the
title page, and finds procedures, equipment, systems and safety reporting by
keyword. Every item records the page it was found on so reviewers can check it.
Confidence reflects how many pages mention the item, not any deeper analysis.
"""

import re
from collections import Counter

import pymupdf


class ExtractionError(Exception):
    """The PDF can't be read or has no usable text."""


# ---------- reading the PDF ----------

def _spaced_out(text: str) -> bool:
    # Some PDFs extract as "C LI NI C A L". Real prose has few one-letter words.
    words = re.findall(r"[A-Za-z]+", text)
    return len(words) > 200 and sum(len(w) == 1 for w in words) / len(words) > 0.25


def read_pdf(data: bytes):
    try:
        doc = pymupdf.open(stream=data, filetype="pdf")
    except Exception as e:
        raise ExtractionError("That file couldn't be opened as a PDF.") from e
    if doc.needs_pass:
        raise ExtractionError("That PDF is password protected.")

    pages = [p.get_text() for p in doc]
    flags = 0
    if _spaced_out(" ".join(pages[:10])):
        flags = pymupdf.TEXT_INHIBIT_SPACES
        pages = [p.get_text(flags=flags) for p in doc]

    if sum(len(t.strip()) for t in pages) < 100 * len(pages):
        raise ExtractionError(
            "This PDF has little or no selectable text, so it's probably a scan. OCR isn't supported yet."
        )
    return doc, pages, flags


def _flat(text: str) -> str:
    # Lowercase with all whitespace collapsed, so phrases split across lines still match.
    return re.sub(r"\s+", " ", text).lower()


def _is_toc(text: str) -> bool:
    return len(re.findall(r"\.{5,}", text)) >= 8


# ---------- study header ----------

BOILERPLATE = re.compile(
    r"^(title page|page \d+|.*\bprotocol\b.{0,15}|.*\b(version|rev\.?|amendment|effective date|confidential)\b.*"
    r"|pi:.*|.*\bproject|ind\b.*|[\w-]+\s*\d[\w-]*)$",
    re.I,
)


def _title_lines(doc, flags):
    """Page-1 lines as (text, size, bold), skipping empty ones."""
    d = doc[0].get_text("dict", flags=pymupdf.TEXTFLAGS_DICT & ~pymupdf.TEXT_PRESERVE_IMAGES | flags)
    out = []
    for b in d["blocks"]:
        for line in b.get("lines", []):
            t = re.sub(r"\s+", " ", "".join(s["text"] for s in line["spans"])).strip()
            if t:
                sz = round(max(s["size"] for s in line["spans"]))
                bold = any(s["flags"] & 16 for s in line["spans"])
                out.append((t, sz, bold))
    return out


def find_title(doc, pages, flags):
    lines = _title_lines(doc, flags)

    # 1. An explicit "Protocol Title:" label, followed by the title text.
    for i, (t, *_ ) in enumerate(lines):
        if re.fullmatch(r"(protocol |official |study )?title:?", t, re.I):
            parts = []
            for t2, *_ in lines[i + 1:]:
                if t2.endswith(":"):
                    break
                parts.append(t2)
            if parts:
                return " ".join(parts)

    # 2. The longest run of same-styled, large-ish lines, minus boilerplate.
    if not lines:
        return None
    big = sorted({sz for _, sz, _ in lines})[-2:]  # two largest sizes on the page
    runs, cur, style = [], [], None
    for t, sz, bold in lines:
        st = (sz, bold)
        if st != style or t.endswith(":"):
            if cur:
                runs.append((style, cur))
            cur, style = [], st
        if t.endswith(":") or BOILERPLATE.match(t):
            continue
        cur.append(t)
    if cur:
        runs.append((style, cur))
    def words(r):
        return len(" ".join(r).split())

    runs = [
        (st, r) for st, r in runs
        if (st[0] in big or st[1]) and 5 <= words(r) <= 60 and not re.search(r"confidential|proprietary", " ".join(r), re.I)
    ]
    if not runs:
        return None
    best = max(runs, key=lambda x: (x[0][0], x[0][1], words(x[1])))[1]
    title = re.sub(r"-\s+(?=\w)", "-", " ".join(best))  # rejoin words hyphenated across lines
    return _title_case(title) if title.isupper() else title


SMALL_WORDS = {"a", "an", "and", "as", "at", "by", "for", "in", "of", "on", "or", "plus", "the", "to", "versus", "vs", "with", "without"}


COMMON_SHORT = {"all", "age", "are", "arm", "day", "end", "low", "may", "new", "non", "not", "one", "per", "six", "ten", "two", "use"}


def _title_case(text):
    # For all-caps titles. Leaves codes like DS-8201A or V600E alone.
    def part(p, first, alone):
        acronym = alone and len(p) <= 3 and p.isalpha() and p.lower() not in SMALL_WORDS | COMMON_SHORT
        if re.search(r"\d", p) or acronym:
            return p
        if not first and p.lower() in SMALL_WORDS:
            return p.lower()
        return p.capitalize()

    def word(w, first):
        parts = w.split("-")
        if len(parts) > 1 and all(re.search(r"\d", p) or len(p) <= 3 for p in parts):
            return w  # a code like DS-8201A
        return "-".join(part(p, first and j == 0, len(parts) == 1) for j, p in enumerate(parts))

    return " ".join(word(w, i == 0) for i, w in enumerate(text.split()))


def _labeled(text, label):
    m = re.search(rf"{label}\s*:\s*\n?\s*([^\n]+)", text, re.I)
    return m.group(1).strip() if m else None


ROMAN = {"i": "1", "ii": "2", "iii": "3", "iv": "4"}


def find_phase(front):
    v = _labeled(front, r"\bphase")
    m = re.match(r"(\d|iv|i{1,3})([ab])?\b", v or "", re.I)
    if not m:
        m = re.search(r"\bphase\s+(\d|iv|i{1,3})([ab])?\b", front, re.I)
    if not m:
        return None
    n = ROMAN.get(m.group(1).lower(), m.group(1))
    return f"Phase {n}{(m.group(2) or '').lower()}"


def find_registry_id(pages, filename):
    first = Counter(re.findall(r"NCT\d{8}", " ".join(pages[:3])))
    if first:
        return first.most_common(1)[0][0]
    m = re.search(r"NCT\d{8}", filename or "", re.I)
    if m:
        return m.group(0).upper()
    num = _labeled(" \n".join(pages[:2]), r"protocol (?:number|no\.?|identifier)")
    return num


def find_sponsor(front):
    v = _labeled(front, r"\bsponsor(?: legal address| name)?")
    if v and not re.search(r"medical monitor|signature|@", v, re.I):
        return v
    m = re.search(
        r"(?:proprietary (?:information )?(?:to|of)|property of|belonging to)\s+([A-Z][^.,;:(“\"\n]{1,40})",
        front,
    )
    return m.group(1).strip() if m else None


DESIGN_TERMS = [
    ("non-randomized", r"non-?randomi[sz]ed"),
    ("randomized", r"(?<!non-)(?<!non)randomi[sz]ed"),
    ("double-blind", r"double-?blind"),
    ("single-blind", r"single-?blind"),
    ("open-label", r"open-?label"),
    ("placebo-controlled", r"placebo-?controlled"),
    ("single arm", r"single[- ]arm"),
    ("multicenter", r"multi-?cent(er|re)"),
    ("first-in-human", r"first[- ]in[- ]human"),
    ("feasibility", r"feasibility"),
]


def find_design(title, pages):
    # Prefer the protocol's own sentence, e.g. "This is a Phase 1, open-label ... study".
    for text in pages[:40]:
        if _is_toc(text):
            continue
        m = re.search(r"\bthis is an? ((?:[\w,()/-]+\s+){2,30}?)(study|trial)\b", re.sub(r"\s+", " ", text), re.I)
        if m:
            design = (m.group(1) + m.group(2)).strip()
            return design[0].upper() + design[1:]
    found = [name for name, pat in DESIGN_TERMS if re.search(pat, title or "", re.I)]
    return ", ".join(found).capitalize() if found else None


def find_enrollment(pages):
    # Multi-part studies list several counts; the largest planned one is the study total.
    best = None
    count = re.compile(
        r"\b(\d{1,3}(?:,\d{3})+|\d{2,5})\s+(?:\w+\s+){0,2}?"
        r"(?:participants|subjects|patients|women|men|veterans|children|individuals)\b",
        re.I,
    )
    for text in pages[:20]:
        text = re.sub(r"\s+", " ", text)
        for m in count.finditer(text):
            # The sentence the count is in.
            start = text.rfind(". ", 0, m.start()) + 1
            end = text.find(". ", m.end())
            sentence = text[start: end if end != -1 else None]
            # Planned counts only: "will be enrolled", "anticipate enrolling", "sample size of".
            planned = re.search(r"will be (enrolled|randomi[sz]ed)|anticipate enrolling|plan(ned)? to enrol|sample size|maximum of", sentence, re.I)
            if planned and not re.search(r"screen", text[max(start, m.start() - 60): m.end() + 40], re.I):
                best = max(best or 0, int(m.group(1).replace(",", "")))
    return best


# ---------- keyword items ----------

PROCEDURES = [
    ("Informed consent", "Regulatory", r"informed consent"),
    ("Eligibility review", "Regulatory", r"inclusion criteria|eligibility criteria"),
    ("Randomization", "Regulatory", r"(?<!non-)(?<!non)\brandomi[sz]ation\b"),
    ("Medical history", "Clinical", r"medical history"),
    ("Physical examination", "Clinical", r"physical exam(ination)?s?\b"),
    ("Vital signs", "Clinical", r"vital signs?"),
    ("Height and weight", "Clinical", r"height (and|,) (body )?weight|weight (and|,) height"),
    ("Concomitant medication review", "Clinical", r"concomitant (medications?|therap)"),
    ("Adverse event assessment", "Safety", r"adverse events?"),
    ("12-lead ECG", "Cardiac", r"\becgs?\b|electrocardiogra(m|ph)"),
    ("Echocardiogram or MUGA scan", "Cardiac", r"echocardiogra|\bmuga\b"),
    ("Hematology", "Lab", r"hematology|haematology|complete blood count|\bcbc\b"),
    ("Serum chemistry", "Lab", r"(serum|blood|clinical) chemistry|metabolic panel"),
    ("Coagulation", "Lab", r"coagulation|prothrombin time"),
    ("Urinalysis", "Lab", r"urinalysis"),
    ("Pregnancy test", "Lab", r"pregnancy tests?"),
    ("Pharmacokinetic sampling", "Lab", r"pharmacokinetic (blood )?(samples?|sampling)|\bpk (blood )?(samples?|sampling)"),
    ("Tumor biopsy or tissue sample", "Lab", r"tumou?r (tissue|biops)|archival tissue|fresh biops"),
    ("CT or MRI imaging", "Imaging", r"computed tomography|\bct scans?\b|\bmri\b|magnetic resonance imaging|\brecist\b"),
    ("Angiography", "Imaging", r"angiogra(m|phy)"),
    ("Ultrasound", "Imaging", r"ultrasound|duplex"),
    ("Chest X-ray", "Imaging", r"chest x-?rays?|chest radiograph"),
    ("Spirometry", "Pulmonary", r"spirometry|\bfev1\b"),
    ("Sleep study", "Pulmonary", r"polysomnograph|sleep study|home sleep (apnea )?test"),
    ("Oral food challenge", "Allergy", r"food challenge|\bdbpcfc\b"),
    ("Skin prick test", "Allergy", r"skin prick tests?"),
    ("Ophthalmologic exam", "Clinical", r"ophthalmolog"),
    ("Questionnaires", "Assessment", r"questionnaires?|patient[- ]reported outcomes?"),
    ("Study drug administration", "Study drug", r"(study drug|investigational product|study intervention) (administration|dosing)|administ\w+ of (the )?(study drug|investigational product)"),
    ("Device implantation", "Study device", r"(device|graft|stent) (implant|placement|deployment)"),
]

EQUIPMENT = [
    ("Refrigerated centrifuge", "Process blood samples", r"centrifug"),
    ("-70/-80 °C freezer", "Store frozen samples", r"(-|−|minus )\s?(70|80)\s?°?\s?c\b|ultra-?low freezer"),
    ("2-8 °C refrigerator", "Store study drug or samples", r"\b2\s?°?\s?c?\s?(-|–|to)\s?8\s?°\s?c\b"),
    ("Temperature monitoring", "Log storage temperatures and excursions", r"temperature (log|monitor|excursion)"),
    ("Dry ice shipping supplies", "Ship frozen samples to central lab", r"dry ice"),
    ("ECG machine", "12-lead ECGs", r"\b12-lead\b"),
    ("Spirometer", "Lung function testing", r"spirometer|spirometry"),
    ("Infusion pump", "IV study drug administration", r"infusion pump|intravenous infusion|\biv infusion"),
    ("Calibrated scale and stadiometer", "Height and weight", r"stadiometer|calibrated scale"),
    ("Emergency medications and equipment", "Treat anaphylaxis or reactions on site", r"epinephrine|anaphyla\w* (kit|treatment)|resuscitation equipment|crash cart"),
    ("CPAP device", "Sleep apnea treatment", r"\bcpap\b|positive airway pressure"),
]

TECHNOLOGY = [
    ("EDC system", "Electronic case report forms", r"electronic data capture|\bedc\b|\becrfs?\b|electronic case report form"),
    ("IRT / IWRS", "Randomization and drug supply", r"\b(irt|iwrs|ixrs|ivrs)\b|interactive (web|voice) response|interactive response technology"),
    ("ePRO / eDiary", "Participant-reported data", r"\bepro\b|\be-?diar(y|ies)\b|electronic diar(y|ies)"),
    ("REDCap", "Study database", r"redcap"),
    ("Central lab portal", "Lab kits, requisitions and results", r"central (laboratory|lab)\b"),
    ("Central imaging upload", "Send scans for central review", r"blinded independent central review|\bbicr\b|central (imaging|reader|radiology) (review|vendor|read)"),
    ("Telehealth platform", "Remote visits", r"telehealth|telemedicine|video visits?"),
    ("Actigraphy / wearables", "Activity or sleep monitoring", r"actigraph|wearable|accelerometer"),
]

PHARMACY = [
    ("Storage conditions for study drug", r"stored? (at|between|refrigerated|in a (secure|locked))"),
    ("Drug accountability and dispensing records", r"(drug|product|study intervention) accountability|dispensing (log|record)"),
    ("Preparation or reconstitution", r"reconstitut|preparation of (the )?(study drug|investigational product|study intervention|infusion)"),
    ("Blinding and emergency unblinding", r"unblind"),
]


def _scan(pattern, flat_pages, skip):
    """Pages (1-based) that match, and the page with the most matches."""
    rx = re.compile(pattern, re.I)
    hits = {}
    for i, text in enumerate(flat_pages):
        if i in skip:
            continue
        n = len(rx.findall(text))
        if n:
            hits[i + 1] = n
    if not hits:
        return [], None
    best = max(hits, key=lambda p: (hits[p], -p))
    return sorted(hits), best


def _confidence(n_pages):
    # More pages mentioning it means it's more likely a real study requirement.
    return 0.85 if n_pages >= 5 else 0.72 if n_pages >= 2 else 0.55


def _pages_note(found):
    shown = ", ".join(map(str, found[:6])) + ("…" if len(found) > 6 else "")
    one = len(found) == 1
    return f"Found by keyword on {len(found)} page{'' if one else 's'} ({shown})." + (
        " Mentioned only once, so it may not be a study requirement." if one else ""
    )


def keyword_items(table, flat_pages, skip, make):
    items = []
    for row in table:
        found, best = _scan(row[-1], flat_pages, skip)
        if found:
            items.append({**make(row), "source_page": best, "confidence": _confidence(len(found)), "notes": _pages_note(found)})
    return items


# ---------- safety reporting ----------

TIMELINE = re.compile(
    r"within (\d+|one|two|three|five|seven|ten|fifteen|twenty-four|twenty four) (calendar |business |working )?(hours?|days?)",
    re.I,
)


def _timeline_near(pattern, flat_pages, skip):
    rx = re.compile(pattern, re.I)
    seen = Counter()
    first_page = {}
    for i, text in enumerate(flat_pages):
        if i in skip:
            continue
        for m in rx.finditer(text):
            window = text[max(0, m.start() - 250): m.end() + 250]
            for t in TIMELINE.finditer(window):
                key = t.group(0).lower()
                seen[key] += 1
                first_page.setdefault(key, i + 1)
    if not seen:
        return None, None
    key, _ = seen.most_common(1)[0]
    return key[0].upper() + key[1:], first_page[key]


SAFETY = [
    ("Serious adverse event (SAE)", "Sponsor", r"serious adverse events?|\bsaes?\b"),
    ("Pregnancy", "Sponsor", r"pregnan\w*"),
    ("Unanticipated problem", "IRB", r"unanticipated problems?"),
    ("Device deficiency or malfunction", "Sponsor", r"device (deficienc|malfunction)"),
]


def safety_items(flat_pages, skip):
    items = []
    for event, recipient, pat in SAFETY:
        found, best = _scan(pat, flat_pages, skip)
        if not found:
            continue
        timeline, tl_page = _timeline_near(pat, flat_pages, skip)
        note = _pages_note(found)
        if not timeline:
            note += " No reporting deadline found nearby; check the safety section."
        items.append({
            "event": event,
            "timeline": timeline or "Not found",
            "recipient": recipient,
            "method": "See protocol",
            "source_page": tl_page or best,
            "confidence": 0.8 if timeline and len(found) >= 2 else 0.6,
            "notes": note,
        })
    oversight, best = _scan(r"data (and )?safety monitoring (board|committee)|\bdsmb\b|data monitoring committee|\bidmc\b", flat_pages, skip)
    if oversight:
        items.append({
            "event": "DSMB / DMC review",
            "timeline": "Per committee charter",
            "recipient": "Data monitoring committee",
            "method": "See protocol",
            "source_page": best,
            "confidence": _confidence(len(oversight)),
            "notes": _pages_note(oversight),
        })
    return items


# ---------- plan ----------

def extract_plan(data: bytes, filename: str) -> dict:
    doc, pages, flags = read_pdf(data)
    flat_pages = [_flat(t) for t in pages]
    skip = {i for i, t in enumerate(pages) if _is_toc(t)}
    front = "\n".join(pages[:3])

    title = find_title(doc, pages, flags)
    registry_id = find_registry_id(pages, filename)
    short = _labeled(front, r"short title")
    if short and short.count("(") > short.count(")"):
        short = short[: short.index("(")].strip()

    drugish, _ = _scan(r"investigational (medicinal )?(product|drug)|study (drug|medication)|\bimp\b", flat_pages, skip)
    pharmacy_involved = len(drugish) >= 3
    pharmacy_items = (
        keyword_items(PHARMACY, flat_pages, skip, lambda r: {"item": r[0]}) if pharmacy_involved else []
    )

    return {
        "id": registry_id or filename,
        "is_sample": False,
        "extraction": "keyword",
        "protocol": {
            "title": title or filename,
            "short_title": short or registry_id or re.sub(r"\.pdf$", "", filename, flags=re.I),
            "registry_id": registry_id,
            "phase": find_phase(front),
            "sponsor": find_sponsor(front),
            "therapeutic_area": None,
            "design": find_design(title, pages),
            "enrollment": find_enrollment(pages),
            "duration": None,
            "pages": len(pages),
        },
        "visits": [],
        "procedures": keyword_items(
            PROCEDURES, flat_pages, skip, lambda r: {"name": r[0], "category": r[1], "visits": []}
        ),
        "staffing": [],
        "safety": safety_items(flat_pages, skip),
        "billing": [],
        "equipment": keyword_items(EQUIPMENT, flat_pages, skip, lambda r: {"item": r[0], "purpose": r[1]}),
        "pharmacy": {"involved": pharmacy_involved, "items": pharmacy_items},
        "technology": keyword_items(TECHNOLOGY, flat_pages, skip, lambda r: {"system": r[0], "purpose": r[1]}),
    }
