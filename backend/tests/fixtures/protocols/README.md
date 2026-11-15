# Protocol test set (issue #15)

Public clinical trial protocols with hand-checked answer files. `backend/eval.py` (issue #35) scores
the extractors against them. The regular `pytest` run never opens this folder.

**3 protocols added, all answer files have been verified by a human curator.**

## Layout

```
protocols/
└── NCT01234567/
    ├── protocol.pdf    # the public protocol, exactly as downloaded
    ├── expected.json   # the answer file (format below)
    └── source.txt      # the ClinicalTrials.gov URL the PDF came from
```

The folder name is the NCT ID. `eval.py` skips any folder that is missing `protocol.pdf` or `expected.json`.

## Answer file format

Every category is required. Use `[]` when the protocol has nothing for it. Field names match
`backend/models.py`, and the format is checked by the `Expected` model in `eval.py`.

```json
{
  "status": "DRAFT – NEEDS HUMAN VERIFICATION",
  "verified_by": null,
  "verified_on": null,
  "nct_id": "NCT01234567",
  "source_url": "https://clinicaltrials.gov/study/NCT01234567",
  "visits": [{"id": "V1", "name": "Screening"}],
  "procedures": [{"name": "ECG", "visits": ["V1"]}],
  "staffing": [{"role": "Principal Investigator"}],
  "safety": [{"event": "Serious adverse event"}],
  "billing": [{"item": "ECG"}],
  "equipment": [{"item": "12-lead ECG machine"}],
  "pharmacy": [{"item": "Investigational product storage"}],
  "technology": [{"system": "EDC"}]
}
```

`procedures[].visits` lists the visit `id`s from this file's own `visits` list. The ids don't have to
match the extractor's ids, because `eval.py` aligns visits by name first.

## Verification rule

A new answer file always starts as a **draft** (`"status": "DRAFT – NEEDS HUMAN VERIFICATION"`). A
person checks every item against the PDF, then sets:

- `"status": "VERIFIED"`
- `"verified_by"`: their initials
- `"verified_on"`: the date, `YYYY-MM-DD`

`eval.py` won't print results while any answer file is a draft. `--allow-draft` prints them, with
every row labeled `UNVERIFIED DRAFT, NOT A RESULT`.

## How the set varies

The protocols should differ in at least two of these. Fill the table in as protocols are added.

| NCT ID | Pages | Phase | Therapeutic area | Schedule layout |
| --- | --- | --- | --- | --- |
| NCT03872401 | 122 | Phase 3 | Cardiovascular (evolocumab, outcomes trial) | One 3-page grid; columns are treatment *years* with Q2W/Q16W cells and "continually" spans; 7 visits |
| NCT07601516 | 60 | Phase 4 (real-world) | Neurology (deutetrabenazine, Huntington's chorea) | One-page week-by-week grid; alternating clinic visits and phone contacts plus an unscheduled column; 10 visits |
| NCT07450833 | 102 | Phase 1 (first in human) | Healthy volunteers (benfo-oxythiamine PK) | Two separate day-by-day grids (SAD and MAD) with inpatient confinement days; 19 visits |

## Curation choices

Each `expected.json` has a `curation_notes` list (ignored by `eval.py`) saying which tables it was
built from and how edge cases were handled. The rules shared by all three:

- **Visits** are the columns of the protocol's schedule table.
- **Procedure→visit**: every marked cell counts, including optional, subset-only and "as available" cells.
- **Staffing** lists site roles only (no sponsor, CRO or committee roles). When the protocol only says
  "study site staff" or "research delegates", the answer file uses "Clinical research coordinator" and
  says so in `notes`.
- **Billing** is `[]` because it needs a coverage analysis. Ignore the billing rows in `eval.py` output.
- Safety, equipment, pharmacy and technology list only items the protocol states directly.
- `source_page` values are PDF page numbers, which can be off by one from the printed page.
