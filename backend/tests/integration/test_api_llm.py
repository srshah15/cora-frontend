"""TestClient tests for upload -> extraction -> validation -> API response,
with the LLM mocked (issues #20, #21, #22, #31)."""

import logging
import time

import main
from extractor import get_extractor
from models import OperationalPlan


def _upload(client, data, name="sample_protocol.pdf"):
    return client.post("/api/protocols", files={"file": (name, data, "application/pdf")})


def test_llm_upload_returns_schema_valid_plan(client, llm_mode, llm_payload, sample_pdf_bytes):
    llm_mode.queue(llm_payload)
    r = _upload(client, sample_pdf_bytes)
    assert r.status_code == 200, r.text

    plan = OperationalPlan.model_validate(r.json())
    assert plan.extraction == "llm"
    assert len(plan.visits) == 3 and plan.staffing and plan.procedures
    assert plan.procedures[0].visits == ["V1"]
    assert plan.extraction_info.model == "claude-opus-5-5"
    # The plan the API returns is accepted as-is by the docx export endpoint.
    r2 = client.post("/api/export/docx", json={"plan": r.json()})
    assert r2.status_code == 200


def test_llm_failure_still_returns_200_with_keyword_plan_and_warning(client, llm_mode, sample_pdf_bytes, api_error):
    llm_mode.queue(api_error("timeout"), api_error("timeout"))
    r = _upload(client, sample_pdf_bytes)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["extraction"] == "keyword"
    assert body["extraction_info"]["fallback"] is True
    assert body["extraction_info"]["reason"] == "timeout"
    assert "took too long" in body["extraction_info"]["warning"]
    assert body["safety"], "the keyword plan is complete"


def test_invalid_key_message_is_specific_and_leaks_nothing(client, llm_mode, sample_pdf_bytes, api_error):
    llm_mode.queue(api_error(401, body={"error": {"message": "bad key sk-ant-LEAKED"}}, message="sk-ant-LEAKED"))
    r = _upload(client, sample_pdf_bytes)
    assert r.status_code == 200
    assert "LLM_API_KEY" in r.json()["extraction_info"]["warning"]  # names the setting, not its value
    assert "LEAKED" not in r.text and "test-key-not-real" not in r.text


def test_malformed_llm_json_falls_back_with_specific_message(client, llm_mode, sample_pdf_bytes):
    llm_mode.queue("{oops")
    body = _upload(client, sample_pdf_bytes).json()
    assert body["extraction_info"]["reason"] == "invalid_output"


def test_ingest_errors_are_rejected_before_any_llm_call(client, llm_mode):
    r = _upload(client, b"this is not a pdf at all", "fake.pdf")
    assert r.status_code == 422
    r = client.post("/api/protocols", files={"file": ("notes.txt", b"hello", "text/plain")})
    assert r.status_code == 400
    assert llm_mode.calls == []


def test_keyword_upload_keeps_source_pages_on_every_section(client, make_pdf):
    # Regression: the response is now validated against OperationalPlan, which
    # must not drop source_page from equipment, technology or pharmacy items.
    text = (
        "Samples are spun in a refrigerated centrifuge and stored on dry ice.\n"
        "Data are entered in the electronic data capture (EDC) system.\n"
        "The investigational product is stored at 2 to 8 C. Study drug accountability\n"
        "records are kept. The investigational product is dispensed by the pharmacy.\n"
        "Study drug is reconstituted before use. Investigational product returns are logged.\n"
    )
    r = _upload(client, make_pdf([text, text, text]))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["equipment"] and all(e["source_page"] for e in body["equipment"])
    assert body["technology"] and all(t["source_page"] for t in body["technology"])
    assert body["pharmacy"]["items"] and all(p["source_page"] for p in body["pharmacy"]["items"])


# ---------- issue #21: limits and timings ----------

def test_too_many_pages_is_a_clear_413(client, make_pdf, monkeypatch, llm_mode):
    monkeypatch.setenv("CORA_MAX_PAGES", "3")
    r = _upload(client, make_pdf(["page text " * 30] * 4))
    assert r.status_code == 413
    detail = r.json()["detail"]
    assert "4 pages" in detail and "up to 3" in detail and "split" in detail
    assert llm_mode.calls == []


def test_default_page_limit_is_150(client, make_pdf):
    assert _upload(client, make_pdf(["page text " * 30] * 151)).status_code == 413


def test_overall_timeout_returns_504_instead_of_hanging(client, sample_pdf_bytes, monkeypatch):
    class SlowExtractor:
        name = "slow"

        def extract(self, parsed, *, deadline=None):
            time.sleep(1.0)
            raise AssertionError("the request should have been abandoned by now")

    monkeypatch.setenv("CORA_REQUEST_TIMEOUT_SECONDS", "0.2")
    main.app.dependency_overrides[get_extractor] = SlowExtractor
    try:
        start = time.monotonic()
        r = _upload(client, sample_pdf_bytes)
        elapsed = time.monotonic() - start
    finally:
        main.app.dependency_overrides.clear()

    assert r.status_code == 504
    assert "took longer than 0.2 seconds" in r.json()["detail"]
    assert elapsed < 0.9  # answered at the timeout, not when the worker finished


def test_stage_timings_are_logged_without_protocol_text(client, llm_mode, llm_payload, sample_pdf_bytes, caplog):
    llm_mode.queue(llm_payload)
    with caplog.at_level(logging.INFO, logger="cora"):
        assert _upload(client, sample_pdf_bytes).status_code == 200

    line = next(m for m in caplog.messages if m.startswith("protocol_processed"))
    for field in ("ingest_ms=", "extract_ms=", "validate_ms=", "respond_ms=", "total_ms=",
                  "pages=1", "method=llm", "fallback=False", "status=200", f"bytes={len(sample_pdf_bytes)}"):
        assert field in line
    for forbidden in ("Synthetic", "Drug X", "NCT00000000", "sample_protocol"):
        assert forbidden not in caplog.text
