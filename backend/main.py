"""FastAPI backend for CORA: receives a protocol PDF and returns a draft operational plan."""

from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, File, HTTPException, Request, Response, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware

from config import load_settings
from docx_export import DOCX_MEDIA_TYPE, DocxExportRequest, build_plan_docx, export_filename
from extract import ExtractionError
from extractors import Extractor, build_extractor

MAX_UPLOAD_BYTES = 50 * 1024 * 1024  # matches the frontend limit

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Fails fast with a ConfigError (e.g. EXTRACTOR=llm without a key) before
    # the server accepts any requests.
    app.state.extractor = build_extractor(load_settings())
    yield

app = FastAPI(lifespan=lifespan)

def get_extractor(request: Request) -> Extractor:
    """The extractor chosen at startup. Tests override this dependency."""
    return request.app.state.extractor

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://[::1]:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    # Lets the frontend read the export filename on cross-origin downloads.
    expose_headers=["Content-Disposition"],
)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/api/protocols")
async def upload_protocol(
    file: UploadFile = File(...), 
    extractor: Extractor = Depends(get_extractor)
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

    try:
        # PDF parsing is CPU-bound, so keep it off the event loop.
        return await run_in_threadpool(extractor.extract, contents, file.filename)
    except ExtractionError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except NotImplementedError as e:
        raise HTTPException(status_code=501, detail=str(e))


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
    )
    return Response(
        content=data,
        media_type=DOCX_MEDIA_TYPE,
        headers={"Content-Disposition": f'attachment; filename="{export_filename(req.plan)}"'},
    )
