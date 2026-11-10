"""TestClient tests for POST /api/export/docx (backend/main.py)."""

import io

from docx import Document

from docx_export import DOCX_MEDIA_TYPE

URL = "/api/export/docx"

REVIEWS = {
    "procedures:10": {"status": "rejected", "comment": "Not needed", "reviewer": "Jane", "at": "2026-11-09T15:05:00Z"},
    "safety:2": {"status": "accepted", "reviewer": "Jane", "at": "2026-11-09T15:06:00Z"},
}


def test_export_returns_openable_docx(client, sample_plan):
    r = client.post(URL, json={"plan": sample_plan, "reviews": REVIEWS, "reviewer": "Jane"})
    assert r.status_code == 200, r.text
    assert r.headers["content-type"] == DOCX_MEDIA_TYPE
    assert r.headers["content-disposition"] == (
        'attachment; filename="xr-214-asthma-phase-ii-operational-plan.docx"'
    )
    doc = Document(io.BytesIO(r.content))
    text = "\n".join(p.text for p in doc.paragraphs)
    assert "Visit schedule" in text
    assert "Reviewed: 1 accepted, 0 edited, 1 rejected" in text


def test_export_without_reviews(client, sample_plan):
    r = client.post(URL, json={"plan": sample_plan})
    assert r.status_code == 200, r.text
    Document(io.BytesIO(r.content))


def test_invalid_plan_returns_422(client, sample_plan):
    sample_plan["procedures"][0]["visits"] = ["V99"]  # unknown visit
    r = client.post(URL, json={"plan": sample_plan, "reviews": {}})
    assert r.status_code == 422
    assert "V99" in r.text


def test_missing_plan_returns_422(client):
    r = client.post(URL, json={"reviews": {}})
    assert r.status_code == 422
    assert any(e["loc"] == ["body", "plan"] for e in r.json()["detail"])


def test_bad_review_key_returns_422(client, sample_plan):
    r = client.post(URL, json={"plan": sample_plan, "reviews": {"procedures:500": {"status": "accepted"}}})
    assert r.status_code == 422
    assert "procedures:500" in r.text
