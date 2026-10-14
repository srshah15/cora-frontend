"""FastAPI backend for CORA: receives a protocol PDF and returns a draft operational plan."""

from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware

from extract import ExtractionError, extract_plan

MAX_UPLOAD_BYTES = 50 * 1024 * 1024  # matches the frontend limit

app = FastAPI()

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
)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/api/protocols")
async def upload_protocol(file: UploadFile = File(...)):
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
        return await run_in_threadpool(extract_plan, contents, file.filename)
    except ExtractionError as e:
        raise HTTPException(status_code=422, detail=str(e))
