# CORA: Clinical Operations Research Assistant

## Repository Layout
- `frontend/`: web app
- `backend/`: FastAPI and extraction code
- `backend/.env.example`: template for future backend configuration
- `.gitignore`: excludes secrets, environments, dependencies, caches, build output, and OS files

## Setup
### Configuration
The backend reads its settings from environment variables, or from `backend/.env` (never committed). All of them are optional.

| Variable | Default | Purpose |
| --- | --- | --- |
| `EXTRACTOR` | `keyword` | `keyword` needs no key and no network. `llm` uses the Claude API. |
| `LLM_API_KEY` | none | Required when `EXTRACTOR=llm`. |
| `LLM_MODEL` | `claude-opus-5-5` | Claude model used for extraction. |
| `LLM_TIMEOUT` | `100` | How long to wait for one LLM response. |
| `CORA_LLM_EFFORT` | `medium` | `low` to `max`. Higher is slower and costs more. |
| `CORA_MAX_PAGES` | `150` | Longer protocols are rejected with HTTP 413. |
| `CORA_REQUEST_TIMEOUT_SECONDS` | `120` | Upper limit for one upload; after it the API answers HTTP 504. |
| `CORA_MAX_OCR_PAGES` | `50` | Most scanned pages read by OCR in one upload. |
| `CORS_ORIGINS` | none | Comma-separated extra origins (the deployed frontend). |
| `DATABASE_URL` | none | PostgreSQL URL (Supabase). Turns on saved plans and reviews; run `alembic upgrade head` in `backend/` first. Without it, nothing is stored. |

If `EXTRACTOR=llm` and the key is missing, the server stops at startup with a message naming the variable.

### How extraction works
1. **Ingest.** The PDF is read in memory. Pages with no text layer are read by OCR if Tesseract is installed.
2. **Extract.** With `EXTRACTOR=llm`, the page-numbered text goes to Claude in one request and comes back as structured JSON. With `keyword`, items and staff roles are found by keyword search, and visits and procedure-to-visit tags are read from the Schedule of Activities table when it is a ruled table. Sections keyword search can't fill (billing, a schedule it couldn't read, no roles found) are flagged for review with the reason.
3. **Validate and merge.** Every item is checked against the plan schema. Items with no source page, no confidence or a bad reference are flagged for review. Sections the LLM left empty are filled from the keyword results.
4. **Fallback.** If the LLM can't be used (timeout, rate limit, bad key, unreadable answer), the request is retried once when that could help, and otherwise the keyword plan is returned with a warning in `extraction_info.warning`.

Uploaded PDFs and protocol text are never written to disk or to logs. The log has one line per upload with page count, method and stage timings only.

Cost: one 100-page protocol is roughly $0.45 to $0.60 with `claude-opus-5-5`.

### OCR for scanned PDFs
OCR uses Tesseract through PyMuPDF. Without it, text PDFs work as usual and scanned PDFs are rejected with a message saying OCR isn't installed.

- macOS: `brew install tesseract`
- Debian/Ubuntu: `sudo apt-get install tesseract-ocr tesseract-ocr-eng`
- Render: deploy `backend/` as a Docker web service. `backend/Dockerfile` installs Tesseract.

If Tesseract is installed somewhere unusual, set `TESSDATA_PREFIX` to its `tessdata` folder.

### Backend
Requires Python 3.13+

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt
cp .env.example .env    # optional; see Configuration below
uvicorn main:app --reload --port 8000
```
The frontend sends uploaded protocol PDFs to a FastAPI backend at `http://localhost:8000`. Check that `http://localhost:8000/health` returns `{"status": "ok"}`.

### Frontend
The frontend is a React app built with Vite and Tailwind. It needs Node 22 or newer. In a second terminal:

```bash
cd frontend
npm ci
cp .env.example .env    # optional; sets VITE_API_BASE and the upload timeout
npm run dev
```
Open http://localhost:5173. The backend URL defaults to `http://localhost:8000`. Change it with `VITE_API_BASE` in `frontend/.env`, or add `?api=https://your-app.onrender.com` to the page URL to change it for one tab.

The old plain-HTML frontend is kept in `frontend/legacy/` until the React app is signed off. Run it with `python3 -m http.server 5174` from that folder.

## Running tests
The backend tests are the automated regression baseline. They don't need an API key or network access, and they don't need the server running.

```bash
cd backend
python3 -m venv .venv            # skip if you already made it during Setup
source .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt
pytest                           # or: pytest -v
pytest -m "not slow"             # skip the large-PDF tests
```

Every run prints a coverage table (`pytest-cov`). The three tests that need a real Tesseract install are skipped when it's missing.

`pytest.ini` puts `backend/` on the import path and collects tests from `tests/`:

```
backend/tests/
├── conftest.py          # shared fixtures: TestClient, sample PDF bytes, synthetic schedule-table PDFs, isolation guards
├── unit/                # pure functions: schema (models.py), PDF text extraction and keyword sections (extract.py, soa.py)
├── integration/         # FastAPI TestClient tests against /health and /api/protocols
└── fixtures/
    ├── make_fixtures.py     # generates the fixture PDFs
    ├── sample_protocol.pdf  # one-page synthetic protocol, no real data
    └── scanned_protocol.pdf # the same page as an image, for OCR tests
```

The fixtures in `conftest.py` block every outbound network connection and unset API keys and `CORA_*` settings for every test, so a real external call fails the test instead of going out, and your own `.env` can't change the results. The Claude client is replaced by a scripted fake (`fake_llm` and `llm_mode` in `conftest.py`).

To regenerate the fixture PDFs after you edit the text in `make_fixtures.py`, run this from `backend/`:

```bash
python tests/fixtures/make_fixtures.py
```

Tests check for known strings from the fixture, such as "Synthetic Test Study of Drug X" and `NCT00000000`, so update them if you change those.

### Frontend tests
```bash
cd frontend
npm test          # Vitest; fetch is stubbed, so no backend is needed
npm run build
```

### CI
`.github/workflows/ci.yml` runs on every push and pull request. The backend job uses Python 3.13 with Tesseract installed, so the OCR tests run too, and runs `pytest`. The frontend job uses Node 22 and runs `npm ci`, `npm test` and `npm run build`. Neither job needs secrets.

### Accuracy evaluation
`backend/eval.py` scores the extractors against the hand-checked protocols in `backend/tests/fixtures/protocols/` (layout and answer-file format in that folder's README):

```bash
cd backend
python eval.py                 # keyword extractor; the LLM column says "not run"
python eval.py --live          # also Claude: needs LLM_API_KEY, shows the estimated cost and asks first
python eval.py --allow-draft   # include unverified answer files, every row labeled as not a result
```

For each category (visits, procedures, staffing, safety, billing, equipment, pharmacy, technology) it prints precision (matched / extracted) and recall (matched / expected). Names are normalized first: lowercase, no punctuation, plurals and a few synonyms folded together. Two names match when at least half their words are shared, and each item can match only one other. Procedure-to-visit links are scored as (procedure, visit) pairs after the visits are aligned. The module docstring has the details. Unverified (draft) answer files are never reported as results.

### Manual check
Click **Try a sample protocol** to load fictional results, then **Download PDF** to check export. To check the full workflow, upload a public, text-based protocol PDF with the backend running.

For a full hands-on test pass, copy the blank template [docs/manual-test-plan.md](docs/manual-test-plan.md) and fill it in as you go.

## API and Data Format

### What the backend needs to provide

| Method | Path | Returns |
| --- | --- | --- |
| `POST` | `/api/protocols` | multipart form with field `file` (the PDF) → plan JSON below |

The PDF export is built in the browser (`pdf-export.js`, using jsPDF), so the backend only has to return JSON.

FastAPI will need CORS enabled for the frontend origin (`CORSMiddleware`).

### Plan JSON

`sample-data.js` is the full reference example. Shape:

```jsonc
{
  "id": "abc123",
  "protocol": { "title", "short_title", "registry_id", "phase", "sponsor",
                "therapeutic_area", "design", "enrollment", "duration", "pages" },
  "visits":     [{ "id": "V1", "name", "day", "window", "type": "Clinic|Phone" }],
  "procedures": [{ "name", "category", "visits": ["V1","V2"], "notes", "source_page", "confidence" }],
  "staffing":   [{ "role", "fte", "responsibilities", "qualifications", "notes", "source_page", "confidence" }],
  "safety":     [{ "event", "timeline", "recipient", "method", "notes", "source_page", "confidence" }],
  "billing":    [{ "item", "designation": "Sponsor|Standard of care|...", "visits", "notes", "confidence" }],
  "equipment":  [{ "item", "purpose", "confidence" }],
  "pharmacy":   { "involved": true, "items": [{ "item", "notes", "confidence" }] },
  "technology": [{ "system", "purpose", "notes", "confidence" }]
}
```

- `confidence` is 0–1. Anything under `reviewThreshold` (0.7, in `config.js`) is flagged for human review.
- `notes` is where the backend explains why something is uncertain. It shows up under the item.
- `source_page` is optional but lets reviewers check the item against the PDF.

### Files

- `index.html`: the three views (upload, processing, results)
- `app.js`: upload handling, rendering, review state
- `pdf-export.js`: builds the downloadable PDF plan (tables, review highlights, sign-off block)
- `styles.css`: light/dark themes, responsive layout, print styles
- `sample-data.js`: fictional sample output (not a real protocol)
- `config.js`: API base URL and review threshold