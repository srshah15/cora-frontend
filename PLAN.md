# CORA implementation plan: LLM extraction, persistence, React frontend, evaluation

## Status (2026-11-11)

| Phase | State |
| --- | --- |
| 1. Extraction pipeline (#16, #18, #20, #22, #31, #21, #23) | Done |
| 2. Persistence (#25, #26, #27) | Done |
| 3. Frontend (#28, #29, #21/#25/#26 frontend, #34, #32) | Done, including CI (`.github/workflows/ci.yml`). **Pending:** parity sign-off, then delete `frontend/legacy/` (#28 PR 5). |
| 4. Evaluation (#15, #35, #33) | `eval.py`, the test-set layout and answer-file format, and `docs/manual-test-plan.md` are done. Answer files cover all 8 categories (decision on open question 4). **Pending:** choose and download the 3 to 5 protocols (including NCT03872401), write their `expected.json`, and verify them by hand. |

## Context

CORA turns clinical trial protocol PDFs into draft operational plans. Today the backend
(`backend/`, FastAPI) only does keyword extraction: it finds procedures, equipment, technology,
pharmacy and safety items, but no visits, staffing or billing. The frontend (`frontend/`) is plain
HTML/JS. This plan covers the 12 target issues plus every open issue they depend on, in four
phases. Each phase runs in its own session, one issue per branch (`feature/<N>-<slug>`).

After approval: copy this plan to `PLAN.md` on branch `chore/plan`, then do **Phase 1 only**, one
issue at a time, running `pytest` after each and stopping for review after each. Ask before pushing
or opening a PR.

## What I found (baseline and surprises)

- **Baseline is green: 48 passed** (`pytest`, run in a throwaway venv outside the repo).
- `gh` is not installed on this machine. I read the issues through the public GitHub REST API. No
  in-scope issue has comments; #14's only comment is "Resolved with commit 24067b4". PRs will have
  to be opened in the browser unless you install `gh` (`brew install gh`).
- Python on this machine is 3.9.6 (system) and 3.15.1 (Homebrew). The README requires 3.13+. Tests
  pass on 3.15.1. There is no `backend/.venv` yet, and `tesseract` is not installed.
- `POST /api/protocols` returns the raw dict from `extract_plan` and has **no `response_model`**,
  although closed #17 says it should. Keyword items carry `source_page` on equipment, technology
  and pharmacy, but those models have no `source_page` field, so validating the response today
  would silently drop it. Fixed in #18 by adding the optional fields.
- `Visit` has no `confidence`, `notes` or `source_page`, which #18 requires. Adding them makes
  visits flaggable, and the current `app.js` would crash in the review queue (`FIELDS.visits` is
  undefined) and `docx_export.REVIEWABLE` excludes visits. Both need a small fix in #18.
- `frontend/app.js` has **no .docx export call**. Only the backend endpoint exists (#24). So it is
  not a parity item; the React port adds a "Download Word" button as new work.
- `python-dotenv` will load a developer's real `.env`. Config must be read at call time, and
  `conftest.py` must also clear the new `CORA_*` variables and `ANTHROPIC_AUTH_TOKEN`.
- Current Claude models (Opus 5.5, Sonnet 5.5) **reject forced tool use** (`tool_choice` any/tool
  returns 400). The supported route is structured outputs: `client.messages.parse(...,
  output_format=<Pydantic model>)`.

## Decisions you made

| Question | Answer |
| --- | --- |
| Persistence authorized by the client? | **Yes.** Phase 2 proceeds. |
| #26 meaning | **Shared plans, private reviews.** `GET /api/plans` lists all plans. "Never mix" = plan IDs never collide and one reviewer's decisions never appear in or overwrite another's. `DELETE /api/plans/{id}` deletes only the caller's decisions on that plan. |
| Model | **`claude-opus-5-5`** default, configurable by env var. |
| Deploy | **Backend on Render (Docker), frontend on Vercel/Netlify.** CORS origins come from an env var. |

## Dependency check (recursive)

| Issue | Role | Depends on (open) |
| --- | --- | --- |
| #16 | prerequisite | none |
| #18 | prerequisite | #16 |
| #20 | prerequisite | #16, #18 |
| #22 | target | #16, #18, #20 |
| #21 | target | #20 (stage timings), frontend part needs #28 |
| #23 | target | none hard; uses the #21 deadline and page cap |
| #31 | target | #16, #18, #20, #22 |
| #25 | target | none (notice needs #28) |
| #26 | target | #25 |
| #27 | target | #25, #26, and #20 (must not store fallback plans) |
| #28 | target | none; must show the #20 warning |
| #29 | prerequisite | #28 |
| #34 | target | #28, #29 |
| #32 | target | #21 (page cap, timeout), #28/#34 (backend-unavailable test) |
| #15 | prerequisite | none |
| #35 | target | #15, #16, #18, #20 |
| #33 | target | none for the blank template |

No dependencies beyond the ones you listed, with two notes. #33 says tests run "on the deployed
build", but deployment has no issue; we only produce the blank template, so nothing is added.
#36 to #40 (docs) are not required by any target and stay out of scope.

## Shared design (Phase 1)

```
upload bytes ─▶ ingest (read_pdf, page cap, OCR for thin pages) ─▶ ParsedDocument
             ─▶ extract (Extractor chosen by env) ─▶ validate + merge ─▶ OperationalPlan ─▶ respond
```

- `ParsedDocument`: `pages: list[str]` (index = page number − 1), `filename`, the open PyMuPDF
  `doc`, `flags`. Built once, passed to every extractor. Lives in memory only.
- `Extractor` is a `typing.Protocol` with `name` and `extract(parsed) -> OperationalPlan`.
  `main.py` imports only `pipeline.run()`, never `anthropic`.
- New env vars (all optional, read at call time): `CORA_EXTRACTOR` (`keyword` default | `claude`),
  `CORA_LLM_MODEL` (`claude-opus-5-5`), `CORA_LLM_TIMEOUT_SECONDS` (50), `CORA_LLM_EFFORT`
  (`medium`), `CORA_MAX_PAGES` (150), `CORA_REQUEST_TIMEOUT_SECONDS` (120), `CORS_ORIGINS`.
  The default stays `keyword`, so behavior is unchanged until someone opts in.
- New backend files: `config.py`, `extractor.py` (interface, `KeywordExtractor`, `get_extractor`),
  `llm_extractor.py` (`ClaudeExtractor`, prompt, error mapping), `llm_schema.py` (the shape the
  model fills in), `pipeline.py` (stages, retry, fallback, timings).
- Schema changes are all optional fields, so old clients and `sample_plan.json` keep validating.

---

## Phase 1: extraction pipeline

Order: #16 → #18 → #20 → #22 → #31 → #21 → #23. Tests for each issue ship in that issue's branch;
the #31 branch adds coverage tooling and fills gaps.

### #16 Claude client, config, extractor interface (prerequisite for #18, #22, #31)
Branch `feature/16-llm-client`.

- **Files:** new `config.py`, `extractor.py`, `llm_extractor.py` (client construction and a stub
  `extract` that #18 fills in); edit `main.py`, `extract.py`, `.env.example`, `requirements.txt`,
  `tests/conftest.py`, README; new `tests/unit/test_config.py`, `tests/unit/test_extractor.py`.
- **Approach:** split `extract_plan` into `read_pdf` (exists) and `plan_from_parsed(parsed)`;
  keep `extract_plan(data, filename)` as a thin wrapper so existing imports and tests still work.
  `get_extractor()` returns the implementation named by `CORA_EXTRACTOR`. `load_dotenv()` runs
  once in `main.py`. The key is checked by us in `os.environ` and passed explicitly to
  `Anthropic(api_key=..., timeout=..., max_retries=0)`. Explicit because the SDK would otherwise
  also accept other credential sources, which would hide a missing key. `max_retries=0` because
  #22 does its own single retry. A FastAPI lifespan hook validates config at startup, so
  `CORA_EXTRACTOR=claude` with no key stops the server with a message naming the variable and
  `backend/.env`.
- **Dependencies:** `anthropic==2.8.0`, `python-dotenv==1.2.4`. I will check `messages.parse` and
  the exception classes against the installed SDK before writing calls.
- **Acceptance criteria:**
  - Key from `.env`, never committed → `load_dotenv`; `.gitignore` already excludes `.env`.
  - `.env.example` added → exists; extended with the new variables and comments.
  - Extractor chosen by env var → `CORA_EXTRACTOR`.
  - Model and timeout configurable → `CORA_LLM_MODEL`, `CORA_LLM_TIMEOUT_SECONDS`.
  - Clear config error when the key is missing in LLM mode → `ConfigError` at startup.
  - Route depends on the interface → `main.py` has no Anthropic import; a test asserts this.
- **Tests:** defaults; env overrides; unknown extractor name; missing key raises `ConfigError`
  without printing any key; keyword mode needs no key; route works with a stub `Extractor`.
- **API/schema changes:** none.
- **Concepts to explain:** interfaces and dependency inversion, env-based config, why secrets
  stay out of git.

### #18 Structured LLM extraction (prerequisite for #20, #22, #31, #35)
Branch `feature/18-llm-extraction`. Two commits: visits, procedures and staffing first, then
safety, billing, equipment, pharmacy and technology.

- **Files:** `llm_schema.py`, `llm_extractor.py`, `models.py`, `main.py` (`response_model`),
  `docx_export.py` (add `visits` to `REVIEWABLE` and field labels), `frontend/app.js` (add a
  `visits` entry to `FIELDS` so flagged visits don't crash the review queue), README,
  `tests/unit/test_llm_extractor.py`, `tests/conftest.py` (fake client).
- **Approach:**
  - Input: every page wrapped as `<page n="12">…</page>`, so the model can cite pages.
  - **Whole document, no chunking.** A 150-page protocol is roughly 75 to 120K tokens, well inside
    the 1M context window. Chunking would split the schedule-of-activities table from the visit
    definitions it refers to and would need a second merge step. The page cap (#21) guarantees
    the fit. Input is never silently truncated; over-limit input fails with a clear error.
  - One request using `client.messages.parse(model, max_tokens=16000, system, messages,
    output_format=LLMPlan, output_config={"effort": ...})`. `LLMPlan` is a lean model where every
    field is required but nullable, which structured outputs handle best.
  - System prompt rules: only report what the protocol states; use null when absent; never
    estimate FTE; give a page for every item; confidence below 0.7 with a note when unsure.
  - Code-side checks, because a prompt alone is not a guarantee: a `source_page` outside
    1..pages is cleared; an item with no page or no confidence is capped at 0.69 with a note; a
    procedure visit tag that matches no visit is dropped with a note; an invalid item is dropped
    and its section flagged in `section_reviews`; an empty visits, procedures or staffing section
    is flagged with a reason. `pages` and the NCT ID come from the PDF and regex, not the model.
  - `stop_reason` of `refusal` or `max_tokens` counts as a failure (handled in #20/#22).
    Anthropic recommends opting into server-side refusal fallback for Opus 5.5
    (`fallbacks="default"`, a beta). I will enable it if `messages.parse` accepts it in SDK 2.8;
    otherwise a refusal goes to the keyword fallback. Say so if you'd rather not use a beta.
  - The result is converted and validated with `OperationalPlan.model_validate`.
- **Cost per protocol (Opus 5.5 at $4 in / $20 out per million tokens):** 100 pages is about 60 to
  80K input tokens ($0.24 to $0.32) plus 10 to 15K output and thinking tokens ($0.20 to $0.30), so
  **about $0.45 to $0.60**, up to about $0.80 at 150 pages. A retry (#22) can double one request.
  Re-uploads cost nothing once #27 lands. Sonnet 5.5 would be about half.
- **Dependencies:** none new.
- **Acceptance criteria:**
  - Matches the Pydantic schema → `model_validate` on every result.
  - Visits with name, timing/window, confidence, source page → new optional `Visit` fields.
  - Procedures tied to correct visit IDs → model emits visit IDs; unknown tags dropped and noted.
  - Staffing roles and stated qualifications → `StaffingRole.qualifications` (already exists).
  - Safety reporting where supported → second commit.
  - Pharmacy, billing, equipment, technology where implemented → second commit.
  - Nothing invented → prompt rules plus the code-side checks above.
  - Low-confidence or incomplete results flagged → 0.69 cap, `section_reviews`.
  - Source page and notes preserved → fields added where missing.
  - Validated before returning → `response_model=OperationalPlan` on the route.
- **Tests (fake client, no network):** valid response maps to a plan; out-of-range page cleared;
  unknown visit tag dropped; missing confidence capped and noted; empty core section flagged;
  prompt contains page markers; keyword upload still returns `source_page` on equipment.
- **Schema changes (all optional):** `Visit.notes/source_page/confidence`;
  `StaffingRole.source_page`; `EquipmentItem/TechnologyItem/PharmacyItem.source_page`.
- **Concepts:** LLM structured output, JSON Schema, why validation still matters, token cost.

### #20 Merge pipeline with keyword fallback (prerequisite for #22, #21)
Branch `feature/20-merge-pipeline`.

- **Files:** new `pipeline.py`; edit `models.py`, `main.py`, `frontend/app.js` (banner), README;
  `tests/unit/test_pipeline.py`, `tests/integration/test_api_llm.py`.
- **Approach:** `pipeline.run(data, filename)`: ingest → LLM extractor → validate → merge. Merge
  rule: the LLM plan is primary; header fields the LLM left null are filled from the keyword
  header; a non-core section the LLM left empty keeps the keyword items (their notes already say
  "Found by keyword"). If the LLM fails for any reason, return the keyword plan with
  `extraction="keyword"` and a warning. `extraction` stays a plain string, so the existing
  "Early draft" note in `app.js` still appears on fallback.
- **Schema change (optional):** `OperationalPlan.extraction_info`: `method` (`llm`|`keyword`),
  `fallback: bool`, `reason` (short code), `warning` (text for the user), `model`,
  `sections` (which method produced each section), `ocr_pages`.
- **Acceptance criteria:**
  - One request returns a complete plan → single `POST /api/protocols`, as today.
  - LLM fails, keyword plan still returns with a notice → fallback path, HTTP 200.
  - Visible warning → `extraction_info.warning`, shown as a banner in `app.js` and later React.
  - Source page, confidence, notes, method metadata preserved → merge never rewrites items;
    `extraction_info.sections`.
- **Tests:** LLM success; LLM raises → keyword plan plus warning; merge fills an empty section
  from keyword; header fill; keyword mode makes zero LLM calls.
- **Concepts:** pipelines, graceful degradation, backward-compatible schema changes.

### #22 LLM failure handling (target)
Branch `feature/22-llm-failures`.

- **Files:** `llm_extractor.py` (error mapping), `pipeline.py` (retry), tests.
- **Approach:** map SDK exceptions to `LLMError(reason, retryable)`, most specific first:
  `APITimeoutError` → `timeout`; `RateLimitError` → `rate_limited`; `APIConnectionError` →
  `connection`; `APIStatusError` with status ≥ 500 → `provider_error` (all four retryable);
  `AuthenticationError`/`PermissionDeniedError` → `invalid_key`; other 4xx → `rejected`; JSON or
  schema failure → `invalid_output`; `refusal`/`max_tokens` → `refused`/`truncated` (not
  retryable). Retry once, after about 1 s with jitter (honoring `retry-after` up to 5 s), and only
  if the request deadline (#21) still has room. Then fall back.
  User messages come from a fixed table keyed by `reason`, for example "The AI service rejected
  CORA's API key, so this plan is keyword-only. Ask your administrator to check
  ANTHROPIC_API_KEY." The exception text is never shown or logged; logs get the reason, HTTP
  status and request ID only.
- **A reading I chose, please confirm:** #22 says invalid key or invalid JSON "returns a specific
  message", and #20 says a failed LLM still returns the keyword plan. I satisfy both by returning
  the keyword plan (HTTP 200) with the specific message in `extraction_info.warning`, not an
  HTTP error.
- **Acceptance criteria:**
  - Retries once on timeout/429/5xx, then falls back → retry loop; tests count calls (exactly 2).
  - Invalid key or invalid JSON gives a specific message → message table.
  - Retries bounded and only for retryable failures → `retryable` flag; 401 and bad JSON get 1 call.
  - No credentials or raw provider responses exposed → fixed messages; a test puts a fake key and
    fake provider body in the exception and asserts neither appears in the response or `caplog`.
- **Tests:** one mocked case per row above, plus "timeout then success" returns the LLM plan.
- **Concepts:** retries and backoff, transient vs permanent errors, safe error messages.

### #31 Mocked-LLM tests and coverage (target)
Branch `feature/31-llm-tests-coverage`.

- **Files:** `tests/conftest.py`, `requirements-dev.txt`, `pytest.ini`, new `.coveragerc`, README.
- **Approach:** `conftest.py` gains a `fake_llm` fixture (a scripted fake Anthropic client
  injected through the one factory function in `llm_extractor.py`) and an `llm_mode` fixture
  (sets `CORA_EXTRACTOR=claude` and a dummy key). The autouse guards also clear `CORA_*` and
  `ANTHROPIC_AUTH_TOKEN`. The network guard stays on, so a real call still fails loudly.
- **Dependencies:** `pytest-cov==7.1.0`, `pytest-mock==3.17.0` (the issue names it; I'd use plain
  `monkeypatch` where it's enough).
- **Acceptance criteria:**
  - No network or key → guards plus fake client.
  - Coverage via `pytest-cov` → `addopts = --cov --cov-report=term-missing`.
  - Valid, partial, malformed JSON, schema-invalid → four named tests. Partial = some items
    invalid: good items kept, section flagged.
  - TestClient covers upload → extraction → validation → response → `test_api_llm.py` checks
    status codes and schema validity for LLM success, fallback and ingest errors.
- **Concepts:** mocking, fixtures, what coverage does and does not tell you.

### #21 Long protocols and response time (target; backend part)
Branch `feature/21-timings-limits`.

- **Files:** `pipeline.py`, `extract.py`, `main.py`, `config.py`, README, tests.
- **Approach:**
  - Stage timings with `time.perf_counter()`; one log line per request, for example
    `protocol_processed pages=87 bytes=1832211 method=llm fallback=False ingest_ms=… extract_ms=…
    validate_ms=… respond_ms=… total_ms=…`. No filename, title or text. `respond` is measured by
    a small middleware as total minus the other stages.
  - Page cap: after opening the PDF and before reading text, more than `CORA_MAX_PAGES` returns
    **413** with "This protocol has N pages. CORA handles up to 150. Remove appendices or split
    the file, then upload again."
  - Overall cap: `asyncio.wait_for(run_in_threadpool(...), CORA_REQUEST_TIMEOUT_SECONDS)` →
    **504** with a clear message.
  - **Threadpool tradeoff:** Python cannot kill a running thread. `wait_for` stops *waiting*; the
    worker keeps going until its current step ends and holds one of the 40 threadpool slots
    until then. So every step gets its own bound (upload size, page cap, SDK timeout), and the
    pipeline receives a deadline that it checks between stages and between OCR pages
    (cooperative cancellation). A killable process pool would be a true cancel but means copying
    PDF bytes between processes and more moving parts; not worth it at this scale.
  - 60 s target: keyword mode is easily inside it. For LLM mode I can only verify it with a real,
    opt-in run using your key. If Opus 5.5 at `medium` effort misses it on long protocols, the
    knobs are `CORA_LLM_EFFORT=low`, then Sonnet 5.5. I will report measured numbers, not assume.
- **Acceptance criteria:**
  - Stage timings for ingestion, extraction, validation/merge, response → the log line.
  - Under 60 s locally → asserted for keyword mode on a generated PDF; LLM mode measured by you
    in an opt-in run and recorded.
  - Over 150 pages completes or fails with a bounded error → 413.
  - Frontend never stuck in processing → backend 504 here; the fetch `AbortController` timeout
    is done in Phase 3 after #28, as you ordered.
- **Tests:** 151-page generated PDF → 413; slow stub extractor with a tiny timeout → 504; `caplog`
  has all four timings and none of the fixture's text.
- **Concepts:** timeouts, event loop vs threadpool, cooperative cancellation.

### #23 OCR fallback (target)
Branch `feature/23-ocr`.

- **Comparison:**

  | | PyMuPDF `page.get_textpage_ocr()` | `pytesseract` |
  | --- | --- | --- |
  | New Python deps | none | `pytesseract` 0.3.13 + Pillow |
  | Needs installed | Tesseract language data | Tesseract binary + language data |
  | How it runs | in-process on a rendered page | subprocess per page, **writes temp image files** |
  | Extras | returns a normal text page, so page handling is unchanged | per-word confidence |

  **Recommendation: PyMuPDF.** No new dependency, and `pytesseract` writing page images to temp
  files conflicts with "never written to disk". I will confirm PyMuPDF writes no temp files
  before relying on it.
- **Files:** `extract.py` (`read_pdf`), `tests/fixtures/make_fixtures.py`, new
  `tests/fixtures/scanned_protocol.pdf`, tests, new `backend/Dockerfile`, README.
- **Approach:** for each page, if stripped text is under a per-page threshold and the page has
  content, OCR that page only and put the text back at the same index. The "little or no text"
  check moves to after OCR. If language data is missing, a scanned PDF returns 422 with "This PDF
  looks scanned and OCR isn't installed on this server" plus the fix. OCR stops at the #21
  deadline and at a page limit (`CORA_MAX_OCR_PAGES`, default 50) with a clear error.
  `extraction_info.ocr_pages` records how many pages were OCR'd.
- **Acceptance criteria:**
  - Scanned test PDF produces a plan → fixture is the sample page rendered to an image-only PDF.
  - Text-native PDFs skip OCR → test asserts the OCR function is never called for the sample PDF.
  - Page numbering preserved → test: text page, scanned page, text page keeps index 2 for OCR text.
  - Setup documented → README: `brew install tesseract` on macOS; Render uses the Dockerfile
    (`apt-get install -y tesseract-ocr tesseract-ocr-eng`, `TESSDATA_PREFIX`).
- **Tests:** the three above, marked to skip when Tesseract is absent; a "scanned but OCR
  unavailable" test using monkeypatch that always runs. No existing test asserts the "OCR isn't
  supported yet" string (I searched `backend/tests`), so there is nothing to update, only to add.
- **Concepts:** text layer vs image, what OCR does, why it is slow and imperfect.

---

## Phase 2: persistence

Order: #25 → #26 → #27. Tests never reach Supabase: they use in-memory SQLite, and the network
guard would fail any real connection.

**Dependencies:** `SQLAlchemy==2.1.8`, `alembic==1.20.1`, `psycopg[binary]==3.3.8`.

**Tables**

| Table | Columns |
| --- | --- |
| `protocols` | `id` UUID PK, `content_hash` CHAR(64) UNIQUE, `nct_id`, `protocol_number`, `version` INT, `title`, `created_at` |
| `plans` | `id` UUID PK, `protocol_id` FK UNIQUE, `plan_json` JSON (JSONB on Postgres), `extraction_method`, `created_at` |
| `reviews` | `id` PK, `plan_id` FK, `reviewer_id`, `reviewer_name`, `item_key`, `status`, `comment`, `values` JSON, `original` JSON, `decided_at`, UNIQUE(`plan_id`, `reviewer_id`, `item_key`) |

**Migrations:** Alembic with one initial migration; `alembic upgrade head` documented and run on
deploy. Tests build the schema with `create_all` on SQLite, and one test runs the Alembic
migration on SQLite so models and migration cannot drift.

**`DATABASE_URL` unset:** uploads and exports work exactly as today and nothing persists
(`plan_id` is null); `/api/plans*` returns 503 "Saving isn't configured on this server".

**Reviewer identity:** headers `X-Reviewer-Id` (a UUID the browser makes once) and
`X-Reviewer-Name`. **This is not authentication.** Anyone who sends another person's ID can read
and change that person's decisions. It only keeps honest users apart. The README will say so.

### #25 Privacy and retention (target)
Branch `feature/25-persistence-models`. Files: new `db.py`, `db_models.py`, `alembic/`,
`repository.py`; edit `main.py`, `models.py`, `.env.example`, README; tests.

- No PDF bytes or raw text in any table or log → the tables have no such column; a test uploads
  the fixture, then scans every row of every table and `caplog` for fixture strings and `%PDF`,
  and checks no file was created.
- "Public protocols only" notice → the upload view already has a similar note; exact wording is
  set in the React upload view (Phase 3).
- ID fields, plans and reviews stored → the tables above. `ProtocolMetadata` gains optional
  `protocol_number`, because `registry_id` currently mixes NCT IDs and protocol numbers.
- Concepts: ORMs, migrations, what a unique constraint buys you.

### #26 Plan and review endpoints (target)
Branch `feature/26-plans-api`. Files: `main.py` (or a new `routes_plans.py`), `repository.py`,
`docx_export.py` (reuse `ReviewDecision` and `validate_review_keys`), tests.

| Endpoint | Behavior |
| --- | --- |
| `GET /api/plans` | all stored plans: id, title, NCT ID, version, created, my review count, other reviewer count |
| `GET /api/plans/{id}` | plan, the caller's reviews only, and the number of other reviewers |
| `PUT /api/plans/{id}/reviews/{item_key}` | upsert the caller's decision; key checked with `validate_review_keys` |
| `DELETE /api/plans/{id}` | delete the caller's decisions on this plan; plan stays |
| `DELETE /api/plans/{id}/reviews/{item_key}` | **addition, not in the issue:** the UI's "Undo decision" needs to remove one decision |

- Reviewers never see or overwrite others' decisions → every query filters on `reviewer_id`;
  tests with two reviewer IDs for read, write and delete.
- Two users' plans never mix → UUID plan IDs; test that reviews on plan A never appear on plan B.
- All bodies Pydantic-validated → request and response models on every route; 422 tests.
- The listed endpoints → table above.
- `ReviewDecision` gains optional `values` (the edited field values). Today the browser edits the
  plan in place; a stored plan must stay unchanged for other reviewers, so an edit is saved with
  the decision and re-applied when that reviewer loads the plan.

### #27 Reuse on re-upload (target)
Branch `feature/27-plan-reuse`. Files: `main.py`, `repository.py`, tests.

- SHA-256 of the uploaded bytes (`hashlib`, in memory), looked up before ingest.
- Hit → stored plan plus this reviewer's reviews, with `reused: true`. Miss → extract, then if
  the NCT ID or protocol number matches an existing row, store with `version = max + 1`.
- `POST /api/protocols` keeps returning the plan JSON, with optional extra fields `plan_id`,
  `reused`, `version`, `reviews`.
- **Fallback plans are not stored** when LLM mode is on, so a temporary provider outage doesn't
  freeze a keyword-only plan for every later upload.
- Two simultaneous uploads of the same file: the unique constraint rejects the second insert,
  which then loads the first one's plan.
- Hashing doesn't require storing the PDF → only the 64-character digest is stored; covered by
  the #25 scan test.
- Second upload makes no LLM call → test asserts the fake client's call count stays at 1.
- Different version extracted fresh → test: different bytes, same NCT ID → new row, version 2,
  second LLM call.
- Concepts: hashing, idempotency, race conditions and constraints.

---

## Phase 3: frontend

Order: #28 → #29 → frontend parts of #21/#25/#26 → #34 → #32.

### #28 React + Vite + Tailwind (target)
Branches `feature/28-react-<part>`, several PRs.

- **Layout:** the first PR moves the six current files to `frontend/legacy/` with `git mv`
  (a move, not a delete; still runnable on another port) and scaffolds the Vite app in
  `frontend/`. Legacy is deleted only in the last PR, after you confirm the checklist.
- **Stack:** Vite 8, React 19, Tailwind 4 (`@tailwindcss/vite`), plain JavaScript/JSX (assumed,
  to match the team; say if you want TypeScript). `jspdf` and `jspdf-autotable` from npm instead
  of the CDN; exact versions pinned by the committed `package-lock.json`.
- **Config:** `VITE_API_BASE` in `.env`, `.env.example` committed; `?api=` still overrides (one
  line). Dev server on 5173, so backend CORS needs no change locally.
- **State:** one `useReducer` in a context (plan, reviews, view, queue position, flagged-only).
  Pure helpers (`isFlagged`, `itemsFor`, `flaggedKeys`, `nextOpen`, section order) live in
  `src/lib/` so they can be unit-tested without rendering.
- **PRs:** (1) scaffold, config, API client, upload and processing views; (2) summary, nav, all
  eight sections; (3) review queue and source pane; (4) PDF export port, new Word export button,
  themes, sample mode; (5) parity sign-off, delete legacy, README.
- **Acceptance criteria:** Vite/React/Tailwind → stack; existing behavior works → checklist
  below; existing API contract → same endpoints and JSON; backend URL from env →
  `VITE_API_BASE`; error and empty states preserved → checklist; old files removed after parity →
  PR 5; deps and lockfile committed → `package.json`, `package-lock.json`; README updated → PR 5;
  fresh clone runs → `npm ci && npm run dev`, which I will test from a clean checkout.

**Parity checklist (every `app.js` behavior)**

Upload
- [ ] Accepts a file by `.pdf` extension or PDF MIME type; otherwise "That doesn't look like a PDF…"
- [ ] Rejects over 50 MB with the existing message, before any request
- [ ] Click to browse, drag and drop with hover state, Enter/Space on the dropzone
- [ ] Sends `multipart/form-data` with field `file` to `POST {apiBase}/api/protocols`
- [ ] Server error shows `detail` (max 200 chars) as "Processing failed. …"
- [ ] Network failure shows "Couldn't reach the backend at {apiBase}…"
- [ ] Every error offers "View sample output instead"
- [ ] `?api=` override

Processing
- [ ] Four steps (Ingestion, Extraction, Structuring, Review check) advancing on a timer, with the file name
- [ ] Remaining steps finish quickly when the response arrives; the timer stops on error

Results
- [ ] Mode pill: "Sample data" or "Draft, needs review"
- [ ] "New protocol" hidden on the upload view; resets plan, reviews, PDF and errors
- [ ] Summary: registry ID and page count, title, facts (phase, sponsor, area, enrollment, design, duration; blanks hidden)
- [ ] Stats: visits, procedures, estimated FTE, items needing review
- [ ] Keyword "Early draft" note, and the #20 fallback warning banner
- [ ] "Review N flagged" button only when there are open flags; "Download PDF"
- [ ] Section nav with open-flag counts; "Only show flagged items" toggle
- [ ] Section pill: "N to review" or "Looks good"
- [ ] Visits timeline (ID, name, day, window, type; phone visits styled differently); empty: "No visits extracted."
- [ ] Procedures grid with sticky first column and a mark per visit; different subtitle when there are no visits; empty: "No procedures extracted."
- [ ] Staffing, safety, billing (designation tags, visit chips), equipment, technology tables; empty: "Nothing found in the protocol for this category."
- [ ] Pharmacy: "is / is not involved" line plus items; empty: "No pharmacy info extracted."
- [ ] Filter on with nothing open: "No open flags here."
- [ ] Each row: confidence bar and percent, notes (warning style when flagged), reviewer comment, "p. N", Review/status button
- [ ] Flag rule: `confidence < 0.7`, numbers only

Review
- [ ] Queue of all flagged items in plan order; opens at the clicked item or the first open one
- [ ] "X of Y reviewed" and progress bar
- [ ] Reviewer name saved to `localStorage` (`cora.reviewer`); a decision without a name focuses the field and shows a toast
- [ ] Editable fields per section, visit checkboxes, designation suggestions, comment box
- [ ] "Accept" becomes "Accept with edits" after a change; edits apply and the original is kept
- [ ] Reject; fields lock after a decision; "Was: …" lines; "Undo decision" restores originals
- [ ] Prev/Next, clickable queue list with status pills, auto-advance to the next open item
- [ ] Shortcuts A, R, ←, → (ignored while typing or with modifier keys)
- [ ] "All flagged items reviewed" screen with counts, Back to plan, Download PDF
- [ ] "Back to plan" scrolls to the item's section
- [ ] Source pane: uploaded PDF at the item's page, "Open in new tab"; sample-mode and no-PDF messages; object URL released on reset

Other
- [ ] Sample mode loads the fictional plan after a short simulated run
- [ ] PDF export: same tables, review highlights, sign-off block, file name from the short title
- [ ] Toasts disappear after 3.5 s
- [ ] Light and dark themes following the system setting; print styles
- [ ] **New, not parity:** "Download Word" calling `POST /api/export/docx`

### #29 Role picker (prerequisite for #34)
Branch `feature/29-role-picker`. Files: `src/lib/roles.js`, results components, PDF export,
backend `docx_export.py` (optional `section_order` in `DocxExportRequest`), tests.

- Each role's sections first → coordinator: visits, procedures; project manager: staffing, safety;
  operations leader: technology, pharmacy, equipment. Billing belongs to no role and stays below.
- Remembered across reloads → `localStorage` key `cora.role`.
- Other sections still accessible → sections become collapsible; the role's are open, the rest
  collapsed but present.
- Order only, not data → ordering is a pure function over section keys; test asserts the plan
  object is unchanged.
- Exports follow the role → the PDF builder takes the ordered list; the docx endpoint takes
  `section_order`, validated as known section keys, defaulting to today's order.

### Frontend parts of #21, #25, #26
Branch `feature/21-25-26-frontend` (or three small branches if you prefer).

- #21: `AbortController` timeout slightly above the backend cap, with "This is taking too long…"
  and a retry hint; 413 and 504 messages shown as given.
- #25: "Public protocols only" notice on the upload view.
- #26/#27: reviewer UUID created once in `localStorage`; headers on every call; reviews loaded
  from the upload response; each decision saved with PUT, undo with DELETE; a "reused saved
  plan" note; if saving fails, the decision stays on screen with a "not saved" warning.

### #34 Frontend tests and CI (target)
Branch `feature/34-frontend-tests`. Dev deps: `vitest` 5, `@testing-library/react` 16,
`@testing-library/user-event`, `@testing-library/jest-dom`, `jsdom`.

- `npm test` green → `vitest run`.
- No backend needed → `fetch` stubbed with `vi.stubGlobal`.
- 0.7 threshold and empty/error states → 0.69 flagged, 0.70 not, non-numeric not; every empty
  state string; unreachable backend, 4xx detail, timeout.
- Also covered: PDF validation, request body (`FormData` field `file`), each section rendering,
  view transitions, role ordering.
- Runs in CI → `.github/workflows/ci.yml` with two jobs: backend (Python 3.13, install Tesseract
  so OCR tests run, `pytest`) and frontend (Node 22, `npm ci`, `npm test`, `npm run build`).

### #32 Error and performance tests (target)
Branch `feature/32-error-perf-tests`. `test_api.py` already covers wrong file type (400), empty
upload (400), oversize (413) and a non-PDF with a `.pdf` name (422); those are not repeated.

| Criterion | Where |
| --- | --- |
| Backend unavailable → clear frontend error | Vitest (written in #34; referenced here) |
| Invalid file types rejected | existing backend test + frontend validation test |
| Over size limit rejected before processing | existing test; add an assertion that the extractor was never called |
| Empty upload rejected without a crash | existing test |
| Normal-sized protocol responsiveness | new: generated ~60-page PDF, keyword mode, under a time bound |
| Longer protocol without failure | new: generated 150-page PDF, marked `slow` |
| Long or oversized input fails clearly | 151 pages → 413 and timeout → 504 (from #21); frontend timeout test |

`slow` is registered in `pytest.ini`; `pytest -m "not slow"` is documented for quick runs.

---

## Phase 4: evaluation

Order: #15 → #35 → #33.

### #15 Protocol test set (prerequisite for #35)
Branch `feature/15-protocol-test-set`.

- I propose 3 to 5 protocols from ClinicalTrials.gov including NCT03872401, chosen to differ in
  length, phase, therapeutic area and schedule layout, and show you the list before downloading.
  Downloading needs your go-ahead since it is a network action.
- Layout: `backend/tests/fixtures/protocols/<NCT>/protocol.pdf` and `expected.json` (visits,
  procedure-to-visit mappings, staffing).
- Every `expected.json` starts with `"status": "DRAFT – NEEDS HUMAN VERIFICATION"`. You verify
  each against its PDF and set `verified_by` and `verified_on`.
- The regular `pytest` run does not process these PDFs.
- Criteria: public and from ClinicalTrials.gov → source URL recorded per protocol; PDFs and JSON
  in fixtures → layout; 3 to 5 including NCT03872401 → list; vary in two ways → a small table in
  the fixtures README; each JSON has visits, mappings, staffing → a schema test.

### #35 Accuracy evaluation (target)
Branch `feature/35-eval`. File: `backend/eval.py`, tests for the metric.

- Runs each protocol through the API in-process (`TestClient`) for the keyword extractor and the
  LLM extractor. The real API run is opt-in (`--live`, needs a key, prints the estimated cost
  first). Without it the LLM column says "not run".
- **Metric (documented in the file and README):** names are lowercased, punctuation stripped, and
  matched by token overlap above a threshold plus a small synonym list; each expected item
  matches at most one extracted item. Precision = matched / extracted, recall = matched /
  expected. Procedure-to-visit is scored on (procedure, visit) pairs after visits are aligned.
- **Unverified drafts are never reported as results.** If any `expected.json` is still DRAFT,
  the script refuses to print a results table unless `--allow-draft` is passed, and then every
  line is labeled "UNVERIFIED DRAFT, NOT A RESULT".
- Criteria: `python eval.py` prints a table → yes; all categories reported with a documented
  metric → the three oracle categories get precision and recall; categories with no oracle
  (safety, billing, equipment, pharmacy, technology) are listed as "no oracle" with item counts.
  See the open question below.

### #33 Manual test template (target)
Branch `feature/33-manual-test-template`. File: `docs/manual-test-plan.md`: a table with tester,
date, environment versions (OS, browser, Python, Node, commit, backend URL), test ID, input,
expected result, actual result, pass/fail. Test cases and expected results are filled in from
the acceptance criteria; **tester, date, actual result and pass/fail are left blank.** The
template says an unexecuted test must be left blank or marked "not run".

---

## Still open (not blocking Phase 1 unless noted)

1. **#22 invalid key / invalid JSON** as a warning on a keyword plan (HTTP 200) rather than an
   HTTP error. This affects Phase 1; I'll build it as described unless you say otherwise.
2. **Refusal fallback beta** (`fallbacks="default"`) in #18: enable if supported, or skip.
3. **#25 "retention"**: the issue title mentions retention but no criterion sets a period or a
   way to delete a plan. Does the client need one?
4. **#35 "all categories"** vs #15's three-category oracle: is "no oracle" acceptable for the
   other five, or should the oracles be extended?
5. **FTE:** protocols almost never state FTE, so LLM staffing will usually have `fte: null` and
   the "est. FTE" stat will read 0. Hide the stat when no FTE is stated?
6. **JavaScript vs TypeScript** for the React app (I assumed JavaScript).
7. **Python version:** this machine has 3.9 and 3.15. Fine to develop on 3.15 and run CI on 3.13?

## Rules I will follow

- `/health`, `POST /api/protocols`, `POST /api/export/docx` and all existing tests keep working.
- All tests run offline with no keys; external services are mocked in `conftest.py`.
- Uploaded PDFs and protocol text are never written to disk, a database or logs.
- Small focused commits on feature branches; README updated whenever setup changes.
- Comments explain why. After each issue I explain the key concepts and stop for your review.
- I ask before pushing or opening a PR ("Closes #N").

## Verification

- After every issue: `cd backend && pytest` (all green, offline), plus the new tests named above.
- Phase 1 manual check: with `CORA_EXTRACTOR=keyword`, upload the sample PDF in the current
  frontend and confirm no change. With `CORA_EXTRACTOR=claude` and no key, confirm the server
  refuses to start with the config message. With your key (opt-in, costs about $0.50 per run),
  upload one public protocol, check visits/procedures/staffing appear with pages and flags, and
  read the timing log line for the 60 s target.
- #23: `brew install tesseract`, then upload `scanned_protocol.pdf` and confirm a plan comes back.
- Phase 2: SQLite tests, then one manual run against Supabase after `alembic upgrade head`.
- Phase 3: `npm test`, `npm run build`, and the parity checklist walked through side by side with
  `frontend/legacy/`.
- Phase 4: `python eval.py` on verified oracles only.
