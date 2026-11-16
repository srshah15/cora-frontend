# CORA: Clinical Operations Research Assistant

CORA reads a clinical trial protocol PDF and drafts an operational plan: visits, procedures, staffing, safety reporting, billing, equipment, pharmacy and technology. A person then reviews and exports the plan.

## Architecture
- **Frontend:** React 19 + Vite 8 + Tailwind 4 (`frontend/`). PDF export is built in the browser (jsPDF).
- **Backend:** FastAPI (`backend/`). Extracts the plan from the PDF and builds the Word (.docx) export.
- **Extractor:** `keyword` (default, offline) or `llm` (Claude API). Users can pick either one per upload when a key is set. OCR for scanned pages uses Tesseract.
- **Database (optional):** PostgreSQL on Supabase stores plans and review decisions. Without it, nothing is saved.
- **Hosting:** backend on Render (Docker), frontend on Vercel.
- **CI:** `.github/workflows/ci.yml` runs the backend and frontend tests on every push and PR.

## Prerequisites
- Git
- Python **3.13+** (`python3 --version`)
- Node **22+** and npm (`node -v`)
- Optional: Tesseract, only needed for scanned (image-only) PDFs
  - macOS: `brew install tesseract`
  - Debian/Ubuntu: `sudo apt-get install tesseract-ocr tesseract-ocr-eng`
- Optional: an Anthropic API key, only needed for AI extraction
- Optional: a Supabase project, only needed to save plans and reviews

## Quick start (local)

**1. Clone**
```bash
git clone https://github.com/srshah15/cora-frontend.git
cd cora-frontend
```

**2. Backend** (terminal 1)
```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt
cp .env.example .env
uvicorn main:app --reload --port 8000
```
- ✅ Verify: `curl http://localhost:8000/health` → `{"status":"ok"}`

**3. Frontend** (terminal 2, from the repo root)
```bash
cd frontend
npm ci
cp .env.example .env
npm run dev
```
- ✅ Verify: open http://localhost:5173, click **Try a sample protocol**, then **Download PDF**.

**4. End-to-end check**
- In the browser, upload `backend/tests/fixtures/sample_protocol.pdf`. A plan should appear.
- Or test the API directly from the repo root:
  ```bash
  curl -F file=@backend/tests/fixtures/sample_protocol.pdf http://localhost:8000/api/protocols
  ```
- ✅ Verify: the response JSON has `"protocol"` and `"extraction_info"` keys.

## Extractor configuration
- `keyword` (default): needs no key or network.
  - Finds items and staff roles by keyword search.
  - Reads visits and procedure-to-visit tags from the Schedule of Activities when it is a ruled table.
  - Sections it can't fill are flagged for review with the reason.
- `llm`: sends the page-numbered text to Claude and gets structured JSON back.
  - For long protocols, only the most relevant pages are sent (title and synopsis, the Schedule of Activities, procedures, safety and so on; see `backend/page_select.py`).
  - Pages keep their original numbers, so source-page citations still match the PDF.
- Server default, set in `backend/.env`:
  ```bash
  EXTRACTOR=llm
  LLM_API_KEY=sk-ant-...
  ```
- **Per-upload choice:** if `LLM_API_KEY` is set, the upload screen offers **AI extraction** or **Keyword search** even when the default is `keyword`. Without a key, only keyword search is available.
- The server **won't start** if `EXTRACTOR=llm` is set without a key. The error names the missing variable.
- Every item is validated against the schema. Items with no source page, low confidence (< 0.7) or a bad reference are flagged for review.
- Sections the LLM left empty are filled from the keyword results.
- Fallback: on a timeout, rate limit, bad key or unreadable answer, CORA retries once if that could help, then returns the keyword plan with a warning in `extraction_info.warning`.
- Cost: about $0.45–$0.60 per 100-page protocol with `claude-opus-5-5`.

## Database (optional)
- Without `DATABASE_URL`: uploads and exports work, nothing is saved, and `/api/plans*` returns **503**.
- To enable saving:
  1. In Supabase, copy the Postgres connection string.
  2. Put it in `backend/.env`:
     ```bash
     DATABASE_URL=postgresql://USER:PASSWORD@HOST:5432/postgres
     ```
  3. Create the tables (also run after any new migration):
     ```bash
     cd backend && source .venv/bin/activate
     alembic upgrade head
     ```
  4. Restart uvicorn.
- ✅ Verify: this returns `{"plans":[...]}`, not a 503 (any UUID works as the reviewer ID):
  ```bash
  curl -H "X-Reviewer-Id: 00000000-0000-0000-0000-000000000001" http://localhost:8000/api/plans
  ```
- Stored: protocol identification fields, the extracted plan, and review decisions. Never stored: the PDF or its text.

## Environment variables

### Backend: `backend/.env` (or the host's env settings)
All are optional. Template: [backend/.env.example](backend/.env.example).

| Variable | Default | Purpose |
| --- | --- | --- |
| `EXTRACTOR` | `keyword` | Server default: `keyword` or `llm` |
| `LLM_API_KEY` | none | Anthropic API key. Required when `EXTRACTOR=llm`, and turns on the AI choice on the upload screen |
| `LLM_MODEL` | `claude-opus-5-5` | Claude model for extraction |
| `LLM_TIMEOUT` | `100` | Seconds to wait for one LLM response |
| `CORA_LLM_EFFORT` | `medium` | `low`, `medium`, `high`, `xhigh` or `max`. Higher is slower and costs more |
| `CORA_MAX_PAGES` | `150` | Longer PDFs are rejected (HTTP 413) |
| `CORA_REQUEST_TIMEOUT_SECONDS` | `120` | Time limit for one upload (HTTP 504 after) |
| `CORA_MAX_OCR_PAGES` | `50` | Most scanned pages OCR'd per upload |
| `CORS_ORIGINS` | none | Comma-separated extra allowed origins, e.g. the Vercel URL. `localhost:5173` is always allowed |
| `DATABASE_URL` | none | Supabase Postgres URL. Turns on saving |
| `TESSDATA_PREFIX` | auto | Tesseract `tessdata` folder, only if Tesseract is installed somewhere unusual |

Invalid values (an unknown extractor or effort, a non-positive number) stop the server at startup with a message naming the variable.

### Frontend: `frontend/.env`
Template: [frontend/.env.example](frontend/.env.example).
- ⚠️ Values are **public** and fixed at **build time**. Never put secrets here, and rebuild after changing them.

| Variable | Default | Purpose |
| --- | --- | --- |
| `VITE_API_BASE` | `http://localhost:8000` | Backend URL |
| `VITE_UPLOAD_TIMEOUT_MS` | `130000` | Browser upload timeout. Keep it a little above `CORA_REQUEST_TIMEOUT_SECONDS` |

- Tip: adding `?api=https://other-backend` to the page URL overrides `VITE_API_BASE` for that tab.

## Deployment

### Backend: Render (Docker)
- New **Web Service** → this repo → **Root Directory** `backend` → **Runtime** Docker.
  - `backend/Dockerfile` installs Tesseract and starts uvicorn on Render's `$PORT`.
- **Health Check Path:** `/health`
- **Environment:** set `EXTRACTOR`, `LLM_API_KEY`, `DATABASE_URL`, and `CORS_ORIGINS` (add this after the frontend is deployed).
- **Migrations:** run `alembic upgrade head` once against the production `DATABASE_URL`, then again after any new migration. You can run it locally with the production URL in `backend/.env`, or from the Render Shell.
- ✅ Verify: `curl https://<your-backend>.onrender.com/health` → `{"status":"ok"}`

### Frontend: Vercel
- New **Project** → this repo → **Root Directory** `frontend` → **Framework Preset** Vite.
  - Build command: `npm run build`. Output directory: `dist`.
- **Environment Variables:** `VITE_API_BASE=https://<your-backend>.onrender.com`, plus `VITE_UPLOAD_TIMEOUT_MS` if you changed the backend timeout.
- Deploy, then add the Vercel URL (e.g. `https://cora.vercel.app`, no trailing slash) to the backend's `CORS_ORIGINS` and redeploy the backend.
- ✅ Verify: open the Vercel URL, upload a protocol, and check that a plan appears with no CORS error in the browser console.

## Testing

### Automated tests
No API key, network or running server needed.

```bash
# Backend
cd backend && source .venv/bin/activate
pytest                    # full suite, with a coverage table
pytest -m "not slow"      # skip the large-PDF tests
```

```bash
# Frontend
cd frontend
npm test                  # Vitest; fetch is stubbed
npm run build             # production build check
```

- The three OCR tests are skipped when Tesseract isn't installed. CI installs it, so they run there.
- The backend tests block outbound network calls and ignore your `.env`. The Claude client is faked (see `backend/tests/conftest.py`).
- To regenerate the fixture PDFs, run `python tests/fixtures/make_fixtures.py` from `backend/`.

### Accuracy evaluation
`backend/eval.py` scores the extractors against hand-checked public protocols in `backend/tests/fixtures/protocols/` (see that folder's README).

```bash
cd backend
python eval.py                 # keyword extractor only
python eval.py --live          # also Claude: needs LLM_API_KEY, shows the cost and asks first
python eval.py --allow-draft   # include unverified answer files, labeled as not results
```

- It prints precision and recall per category. The matching rules are in the module docstring.

### Manual test pass
- For a full hands-on pass, copy [docs/manual-test-plan.md](docs/manual-test-plan.md) and fill it in.
- The end-user guide (coordinator/reviewer quick start and FAQ) is at [frontend/public/quick-start.html](frontend/public/quick-start.html) and is linked from the app.

## API
| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/health` | Liveness check |
| `GET` | `/api/config` | `{default_mode, ai_available}` for the upload screen. Never includes the key |
| `POST` | `/api/protocols` | Multipart: `file` (PDF, ≤ 50 MB), optional `mode` (`llm` or `keyword`) → plan JSON |
| `POST` | `/api/export/docx` | Plan + reviews JSON → Word file |
| `GET` | `/api/plans` | List saved plans (needs DB) |
| `GET` | `/api/plans/{plan_id}` | One saved plan with the caller's reviews |
| `PUT` | `/api/plans/{plan_id}/reviews/{item_key}` | Save a review decision |
| `DELETE` | `/api/plans/{plan_id}/reviews/{item_key}` | Undo a review decision |
| `DELETE` | `/api/plans/{plan_id}` | Delete the caller's decisions on a plan |

- Plan schema: [backend/models.py](backend/models.py). Full example: [frontend/src/data/samplePlan.js](frontend/src/data/samplePlan.js).
- Interactive docs: http://localhost:8000/docs

## Privacy and security
- Uploaded PDFs and their text are never written to disk, logs or the database. Each upload logs one line with page count, method and timings only.
- Reviewers are identified by the `X-Reviewer-Id` and `X-Reviewer-Name` headers. **This is not authentication**: anyone who sends another person's ID can read and change that person's decisions.
- Never commit `.env` files (they are git-ignored). Put production secrets in the Render and Vercel dashboards.

## Troubleshooting
- **`Port 5173 is in use`:** stop the other process. Vite won't switch ports, because the backend's CORS only allows 5173.
- **CORS error in the browser console:** add the frontend's exact origin to `CORS_ORIGINS` and restart the backend.
- **Server exits with `ConfigError`:** fix the variable named in the message in `backend/.env`.
- **No "AI extraction" option on the upload screen, or "AI extraction isn't set up":** set `LLM_API_KEY` and restart the backend.
- **"OCR isn't installed":** the PDF is scanned. Install Tesseract (see Prerequisites) or use the Docker image.
- **HTTP 413:** the PDF has more than `CORA_MAX_PAGES` pages or is over 50 MB.
- **HTTP 504 or a browser timeout:** raise `CORA_REQUEST_TIMEOUT_SECONDS` and `VITE_UPLOAD_TIMEOUT_MS` together.
- **HTTP 400 on `/api/plans`:** send an `X-Reviewer-Id` header containing a UUID.
- **HTTP 503 on `/api/plans`:** `DATABASE_URL` is not set, or `alembic upgrade head` hasn't been run.
- **Frontend still calls the wrong backend:** `VITE_*` values are fixed at build time, so rebuild or redeploy after changing them.

## Repository layout
```
.github/workflows/  CI (backend pytest + frontend test/build)
backend/            FastAPI app, extractors, DB models, Alembic migrations, eval.py, Dockerfile
  tests/            pytest suite (unit/, integration/, fixtures/, fixtures/protocols/)
docs/               manual test plan template
frontend/           Vite + React app
  src/              components/, lib/ (plan, PDF export, roles), api.js, config.js
  public/           end-user quick-start guide (HTML + PDF)
  legacy/           original static prototype, kept until sign-off; not used
PLAN.md             development plan and design decisions
```
