"""This file contains the main application logic for the Protocol Operations backend."""

from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware

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

    return {
        "id": "amgen-demo",
        "is_sample": False,

        "protocol": {
            "title": file.filename,
            "short_title": "Uploaded Protocol",
            "registry_id": "NCT03872401",
            "phase": "Phase 3",
            "sponsor": "Amgen Inc.",
            "therapeutic_area": "Cardiovascular",
            "design": "Randomized, double-blind, placebo-controlled",
            "enrollment": 12000,
            "duration": "Median follow-up ≥ 4.5 years",
            "pages": None,
        },

        "visits": [
            {
                "id": "SCR",
                "name": "Screening",
                "day": "Up to 21 days before Day 1",
                "window": None,
                "type": "Clinic",
            },
            {
                "id": "D1",
                "name": "Day 1",
                "day": "Day 1",
                "window": None,
                "type": "Clinic",
            },
            {
                "id": "Q16W",
                "name": "Treatment Visit",
                "day": "Every 16 weeks",
                "window": "±7 days",
                "type": "Clinic",
            },
        ],

        "procedures": [
            {
                "name": "Informed consent",
                "category": "Regulatory",
                "visits": ["SCR"],
                "source_page": 19,
                "confidence": 0.99,
            },
            {
                "name": "Physical examination",
                "category": "Clinical",
                "visits": ["SCR"],
                "source_page": 19,
                "confidence": 0.65,
            },
            {
                "name": "Investigational product administration",
                "category": "Study drug",
                "visits": ["D1", "Q16W"],
                "source_page": 21,
                "confidence": 0.99,
            },
        ],

        "staffing": [],
        "safety": [],
        "billing": [],
        "equipment": [],
        "pharmacy": {
            "involved": False,
            "items": [],
        },
        "technology": [],
    }