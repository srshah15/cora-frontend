"""FastAPI backend for CORA: receives a protocol PDF and returns a draft operational plan."""

import asyncio
import hashlib
import logging
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

import anyio
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, Header, UploadFile, File, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware

import db
import pipeline
import repository as repo
from api_models import ProtocolResponse
from config import cors_origins, get_settings
from docx_export import DOCX_MEDIA_TYPE, DocxExportRequest, build_plan_docx, export_filename
from extract import ExtractionError, ProtocolTooLongError
from extractor import Extractor, get_extractor
from models import OperationalPlan
from routes_plans import parse_reviewer_id, router as plans_router

log = logging.getLogger("cora.api")

# Load backend/.env into the environment (a no-op if the file doesn't exist).
# The path is anchored to this file so it works from any working directory.
# Real environment variables win over .env, which is what a host like Render
# expects.
load_dotenv(Path(__file__).parent / ".env")

MAX_UPLOAD_BYTES = 50 * 1024 * 1024  # matches the frontend limit


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Check configuration once at startup. A missing key in LLM mode raises
    # ConfigError here, so the server refuses to start with a clear message
    # instead of failing on the first upload.
    get_settings()
    # Make our own INFO lines (stage timings) visible next to uvicorn's.
    logging.getLogger("cora").setLevel(logging.INFO)
    if not logging.getLogger("cora").handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(levelname)s:     %(name)s %(message)s"))
        logging.getLogger("cora").addHandler(handler)
    yield


app = FastAPI(lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    # Local dev origins plus any in CORS_ORIGINS (the deployed frontend).
    allow_origins=cors_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    # Lets the frontend read the export filename on cross-origin downloads.
    expose_headers=["Content-Disposition"],
)


@app.middleware("http")
async def log_stage_timings(request: Request, call_next):
    """Log one line per upload with how long each stage took.

    The route records ingest/extract/validate; whatever remains of the total
    (reading the upload, serializing the plan) is the "respond" stage. The
    line holds numbers and short codes only: no file name, no protocol text.
    """
    start = time.perf_counter()
    response = await call_next(request)
    timings = getattr(request.state, "timings", None)
    if timings is not None:
        total = (time.perf_counter() - start) * 1000
        staged = timings.ingest_ms + timings.extract_ms + timings.validate_ms
        fields = {
            "status": response.status_code,
            "bytes": getattr(request.state, "upload_bytes", 0),
            **timings.as_log_fields(),
            "respond_ms": round(max(total - staged, 0)),
            "total_ms": round(total),
        }
        log.info("protocol_processed " + " ".join(f"{k}={v}" for k, v in fields.items()))
    return response


app.include_router(plans_router)


@app.get("/health")
def health():
    return {"status": "ok"}


def _lookup(content_hash: str, reviewer: Optional[str], llm_mode: bool):
    """Find a stored plan for this exact file. Returns (response, stale_plan_id).

    A keyword-only plan stored before the LLM was switched on is "stale": we
    extract again instead of serving it forever, and replace it afterwards.
    """
    with db.session_scope() as s:
        stored = repo.find_by_hash(s, content_hash)
        if stored is None:
            return None, None
        if llm_mode and stored.extraction_method == "keyword":
            return None, stored.plan_id
        reviews = repo.reviews_for(s, stored.plan_id, reviewer) if reviewer else {}
        return ProtocolResponse(
            **stored.plan_json, plan_id=stored.plan_id, reused=True, version=stored.version, reviews=reviews
        ), None


def _store(content_hash: str, plan: OperationalPlan, stale_plan_id: Optional[str]) -> repo.Stored:
    with db.session_scope() as s:
        if stale_plan_id:
            return repo.replace_plan(s, stale_plan_id, plan)
        return repo.save_plan(s, content_hash, plan)


@app.post("/api/protocols", response_model=ProtocolResponse)
async def upload_protocol(
    request: Request,
    file: UploadFile = File(...),
    # Optional here: without it the upload still works, there are just no
    # saved decisions to return.
    x_reviewer_id: Optional[str] = Header(default=None),
    # The route asks for "an Extractor" and FastAPI supplies whichever one the
    # configuration names. Nothing in this file knows about Claude.
    extractor: Extractor = Depends(get_extractor),
):
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(
            status_code=400,
            detail="Only PDF files are supported",
        )

    contents = await file.read()

    if not contents:
        raise HTTPException(
            status_code=400,
            detail="Uploaded file is empty",
        )

    if len(contents) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=413,
            detail="That file is over 50 MB. Try a smaller protocol or split the appendices out.",
        )

    settings = get_settings()
    request.state.upload_bytes = len(contents)
    reviewer = parse_reviewer_id(x_reviewer_id)
    llm_mode = extractor.name != "keyword"

    # Reuse (issue #27). SHA-256 gives the same 64-character fingerprint for
    # the same bytes and a different one if even one byte changes. We store
    # the fingerprint, never the file, and it can't be reversed into the file.
    # Checking it BEFORE extraction is what makes a repeat upload instant and free.
    content_hash = hashlib.sha256(contents).hexdigest()
    stale_plan_id = None
    if db.is_configured():
        hit, stale_plan_id = await anyio.to_thread.run_sync(_lookup, content_hash, reviewer, llm_mode)
        if hit is not None:
            log.info("protocol_reused plan_id=%s version=%s", hit.plan_id, hit.version)
            return hit
    # A monotonic clock only moves forward, so it is safe for measuring
    # "how long until we give up" (the wall clock can jump).
    deadline = time.monotonic() + settings.request_timeout_seconds

    def process() -> pipeline.Result:
        return pipeline.run(contents, file.filename, extractor, settings, deadline)

    try:
        # PDF parsing is CPU-bound and LLM calls block, so both run in a
        # worker thread, off the event loop.
        #
        # Python can't kill a thread. On timeout we stop *waiting*
        # (abandon_on_cancel) and answer 504; the thread carries on until its
        # current step ends. That is why every step has its own limit (upload
        # size, page cap, SDK timeout) and the pipeline checks the deadline
        # between steps, so an abandoned thread can't run for long.
        result = await asyncio.wait_for(
            anyio.to_thread.run_sync(process, abandon_on_cancel=True),
            timeout=settings.request_timeout_seconds,
        )
    except asyncio.TimeoutError:
        raise HTTPException(
            status_code=504,
            detail=(
                f"Processing took longer than {settings.request_timeout_seconds:g} seconds and was stopped. "
                "Try again, or upload a shorter protocol (remove appendices)."
            ),
        )
    except ProtocolTooLongError as e:
        raise HTTPException(status_code=413, detail=str(e))
    except ExtractionError as e:
        raise HTTPException(status_code=422, detail=str(e))

    request.state.timings = result.timings
    plan = result.plan

    # Don't store a fallback plan: the LLM was wanted but unavailable, and
    # saving the keyword-only result would serve it to every later upload of
    # this file even after the outage ends.
    is_fallback = bool(plan.extraction_info and plan.extraction_info.fallback)
    if db.is_configured() and not is_fallback:
        stored = await anyio.to_thread.run_sync(_store, content_hash, plan, stale_plan_id)
        return ProtocolResponse(
            **stored.plan_json, plan_id=stored.plan_id, version=stored.version,
            # True only if another request stored this same file while we were extracting.
            reused=stored.plan_json != plan.model_dump(mode="json"),
        )
    return ProtocolResponse(**plan.model_dump())


@app.post("/api/export/docx")
def export_docx(req: DocxExportRequest):
    """Build an editable Word draft of the plan with review status marked.

    The body is validated against OperationalPlan (plus review decisions keyed
    "<section>:<index>"), so an invalid plan returns 422. Sync def: FastAPI runs
    it in a threadpool, keeping document building off the event loop.
    """
    data = build_plan_docx(
        req.plan,
        req.reviews,
        review_threshold=req.review_threshold,
        reviewer=req.reviewer,
        section_order=req.section_order,
    )
    return Response(
        content=data,
        media_type=DOCX_MEDIA_TYPE,
        headers={"Content-Disposition": f'attachment; filename="{export_filename(req.plan)}"'},
    )
