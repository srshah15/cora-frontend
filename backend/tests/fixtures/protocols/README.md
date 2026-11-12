# Protocol test set (issue #15)

Public clinical trial protocols with hand-checked answer files. `backend/eval.py` (issue #35) scores
the extractors against them. The regular `pytest` run never opens this folder.

**Status: no protocols added yet.** The set needs 3 to 5 protocols from ClinicalTrials.gov, and it
must include **NCT03872401**.

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
- `"verified_by"`: their name
- `"verified_on"`: the date, `YYYY-MM-DD`

`eval.py` won't print results while any answer file is a draft. `--allow-draft` prints them, with
every row labeled `UNVERIFIED DRAFT, NOT A RESULT`.

## How the set varies

The protocols should differ in at least two of these. Fill the table in as protocols are added.

| NCT ID | Pages | Phase | Therapeutic area | Schedule layout |
| --- | --- | --- | --- | --- |
| NCT03872401 | | | | |
