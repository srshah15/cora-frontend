# CORA: Clinical Operations Research Assistant

## Repository Layout
- `frontend/`: web app
- `backend/`: FastAPI and extraction code
- `backend/.env.example`: template for future backend configuration
- `.gitignore`: excludes secrets, environments, dependencies, caches, build output, and OS files

## Setup
Requires Python 3.13+

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt
cp .env.example .env    # fill in required keys
uvicorn main:app --reload --port 8000
```
The frontend sends uploaded protocol PDFs to a FastAPI backend at
`http://localhost:8000`. Check that `http://localhost:8000/health` returns `{"status": "ok"}`.

The backend URL defaults to `http://localhost:8000`. Point it somewhere else with `?api=https://your-app.onrender.com`, or edit `config.js`.

In a second terminal:

```bash
cd frontend
python3 -m http.server 5173
```
Open http://localhost:5173.

## Configuration
Backend settings come from environment variables; `backend/.env` is loaded for local development (copy `backend/.env.example`). Real environment variables take precedence.

| Variable | Default | Purpose |
| --- | --- | --- |
| `EXTRACTOR` | `keyword` | `keyword` (rule-based, no key needed) or `llm` (Claude) |
| `LLM_API_KEY` | none | Required when `EXTRACTOR=llm`; the server refuses to start without it |
| `LLM_MODEL` | `claude-sonnet-5-5` | Claude model ID |
| `LLM_TIMEOUT` | `60` | Per-request timeout for the Claude API |
| `LLM_RETRIES` | `2` | SDK retries on transient errors |

To add another model provider, implement the `Extractor` interface in `backend/extractors/` and add it to `build_extractor()`. `main.py` doesn't change.

## Running tests
The backend tests are the automated regression baseline. They don't need an API key or network access, and they don't need the server running.

```bash
cd backend
python3 -m venv .venv            # skip if you already made it during Setup
source .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt
pytest                           # or: pytest -v
```

`pytest.ini` puts `backend/` on the import path and collects tests from `tests/`:

```
backend/tests/
├── conftest.py          # shared fixtures: TestClient, sample PDF bytes, isolation guards
├── unit/                # pure functions: schema (models.py), PDF text extraction (extract.py)
├── integration/         # FastAPI TestClient tests against /health and /api/protocols
└── fixtures/
    ├── make_fixtures.py     # generates the fixture PDFs
    └── sample_protocol.pdf  # one-page synthetic protocol, no real data
```

The fixtures in `conftest.py` block every outbound network connection and unset `LLM_API_KEY` for every test, so a real external call fails the test instead of going out. Extraction is keyword-based today. When an LLM step is added, its mock belongs in `conftest.py` too.

To regenerate the fixture PDF after you edit its text in `make_fixtures.py`, run this from `backend/`:

```bash
python tests/fixtures/make_fixtures.py
```

Tests check for known strings from the fixture, such as "Synthetic Test Study of Drug X" and `NCT00000000`, so update them if you change those.

### Manual check
Click **Try a sample protocol** to load fictional results, then **Download PDF** to check export. To check the full workflow, upload a public, text-based protocol PDF with the backend running.

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
  "staffing":   [{ "role", "fte", "responsibilities", "confidence" }],
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