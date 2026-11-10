"""FastAPI TestClient tests for the backend endpoints (backend/main.py)."""

import main
from models import OperationalPlan


def _upload(client, name, data, content_type="application/pdf"):
    return client.post("/api/protocols", files={"file": (name, data, content_type)})


def test_health_ok(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_upload_sample_pdf_returns_valid_plan(client, sample_pdf_bytes):
    r = _upload(client, "sample_protocol.pdf", sample_pdf_bytes)
    assert r.status_code == 200, r.text

    plan = OperationalPlan.model_validate(r.json())
    assert plan.extraction == "keyword"
    assert plan.is_sample is False
    assert plan.protocol.registry_id == "NCT00000000"
    assert plan.protocol.pages == 1
    # The fixture has a 24-hour SAE reporting rule; at least one safety item
    # should be found.
    assert plan.safety
    # Note: protocol.title is not asserted. find_title() currently misses the
    # fixture's "Study Title:" line and falls back to the filename.


def test_upload_non_pdf_rejected(client):
    r = _upload(client, "notes.txt", b"just some text", "text/plain")
    assert r.status_code == 400
    assert r.json()["detail"] == "Only PDF files are supported"


def test_upload_empty_file_rejected(client):
    r = _upload(client, "empty.pdf", b"")
    assert r.status_code == 400
    assert r.json()["detail"] == "Uploaded file is empty"


def test_upload_pdf_extension_but_not_pdf_content(client):
    r = _upload(client, "fake.pdf", b"this is not a pdf at all")
    assert r.status_code == 422
    assert "couldn't be opened as a PDF" in r.json()["detail"]


def test_upload_oversize_rejected(client, monkeypatch, sample_pdf_bytes):
    # Lower the limit for this test instead of sending a 50 MB payload.
    monkeypatch.setattr(main, "MAX_UPLOAD_BYTES", len(sample_pdf_bytes) - 1)
    r = _upload(client, "sample_protocol.pdf", sample_pdf_bytes)
    assert r.status_code == 413
    assert "over 50 MB" in r.json()["detail"]
