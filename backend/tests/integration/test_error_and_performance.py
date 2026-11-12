"""Error-condition and performance tests from the project test plan (issue #32).

Already covered elsewhere, and deliberately not repeated here:
- wrong file type -> 400, empty upload -> 400, oversize -> 413,
  .pdf name with non-PDF content -> 422        (test_api.py)
- more than the page limit -> 413, overall timeout -> 504   (test_api_llm.py)
- backend unavailable -> clear frontend error               (frontend Vitest suite)

The PDFs here are generated in memory with synthetic text. Time bounds are
loose on purpose: they catch "something became very slow or hangs", not small
regressions, so they don't fail on a busy laptop or CI runner.
"""

import time

import pymupdf
import pytest

import main
import pipeline
from models import OperationalPlan

PARAGRAPH = (
    "Participants attend the clinic for vital signs, physical examination, a 12-lead ECG, hematology, "
    "serum chemistry and urinalysis. Adverse events and concomitant medications are reviewed at each visit. "
    "Serious adverse events must be reported to the sponsor within 24 hours of awareness. Data are entered "
    "in the electronic data capture system. Investigational product is stored at 2 to 8 C and drug "
    "accountability records are maintained by the pharmacy. "
)


def _protocol_pdf(n_pages: int) -> bytes:
    doc = pymupdf.open()
    for i in range(n_pages):
        page = doc.new_page()
        header = "Study Title: Synthetic Long Protocol\nRegistry ID: NCT00000001\n" if i == 0 else ""
        page.insert_textbox(pymupdf.Rect(50, 50, 560, 780), header + f"Section {i + 1}. " + PARAGRAPH * 6, fontsize=9)
    data = doc.tobytes()
    doc.close()
    return data


def _upload(client, data, name="protocol.pdf"):
    return client.post("/api/protocols", files={"file": (name, data, "application/pdf")})


def test_normal_sized_protocol_is_processed_promptly(client):
    pdf = _protocol_pdf(60)
    start = time.monotonic()
    r = _upload(client, pdf)
    elapsed = time.monotonic() - start

    assert r.status_code == 200, r.text
    plan = OperationalPlan.model_validate(r.json())
    assert plan.protocol.pages == 60 and plan.procedures and plan.safety
    assert elapsed < 20, f"a 60-page protocol took {elapsed:.1f}s"


@pytest.mark.slow
def test_longest_allowed_protocol_completes_within_the_target(client):
    pdf = _protocol_pdf(150)  # exactly the page limit
    start = time.monotonic()
    r = _upload(client, pdf)
    elapsed = time.monotonic() - start

    assert r.status_code == 200, r.text
    assert r.json()["protocol"]["pages"] == 150
    assert elapsed < 60, f"a 150-page protocol took {elapsed:.1f}s (target: under 60s)"


@pytest.mark.slow
def test_longer_than_allowed_fails_fast_and_clearly(client):
    pdf = _protocol_pdf(200)
    start = time.monotonic()
    r = _upload(client, pdf)
    elapsed = time.monotonic() - start

    assert r.status_code == 413
    assert "200 pages" in r.json()["detail"]
    assert elapsed < 10  # rejected on page count, before reading the text


def test_backend_survives_a_bad_upload_and_keeps_serving(client, sample_pdf_bytes):
    assert _upload(client, b"").status_code == 400
    assert _upload(client, b"%PDF-1.7 truncated garbage").status_code == 422
    assert client.get("/health").json() == {"status": "ok"}
    assert _upload(client, sample_pdf_bytes).status_code == 200


def test_rejected_uploads_never_reach_the_pipeline(client, monkeypatch, sample_pdf_bytes):
    def boom(*args, **kwargs):
        raise AssertionError("the pipeline must not run for a rejected upload")

    monkeypatch.setattr(pipeline, "run", boom)
    monkeypatch.setattr(main, "MAX_UPLOAD_BYTES", len(sample_pdf_bytes) - 1)

    assert _upload(client, sample_pdf_bytes).status_code == 413         # over the size limit
    assert _upload(client, b"").status_code == 400                      # empty
    assert _upload(client, b"hello", "notes.txt").status_code == 400    # wrong type


def test_password_protected_pdf_is_a_clear_422(client):
    doc = pymupdf.open()
    doc.new_page().insert_text((50, 72), "secret")
    data = doc.tobytes(encryption=pymupdf.PDF_ENCRYPT_AES_256, user_pw="pw", owner_pw="pw")
    r = _upload(client, data)
    assert r.status_code == 422
    assert "password protected" in r.json()["detail"]
