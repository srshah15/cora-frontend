"""Tests for the merge pipeline, fallback and retry rules (backend/pipeline.py)."""

import logging

import pytest

import pipeline
from config import get_settings
from extractor import KeywordExtractor, get_extractor

SECRET = "sk-ant-LEAKED-KEY"


def _run(pdf, deadline=None):
    return pipeline.run(pdf, "sample_protocol.pdf", get_extractor(), get_settings(), deadline)


# ---------- keyword mode ----------

def test_keyword_mode_never_calls_the_llm(fake_llm, sample_pdf_bytes):
    result = _run(sample_pdf_bytes)
    plan = result.plan
    assert plan.extraction == "keyword"
    assert plan.extraction_info.method == "keyword"
    assert plan.extraction_info.fallback is False
    assert plan.extraction_info.warning is None
    assert plan.extraction_info.sections["visits"] == "none"
    assert plan.extraction_info.sections["safety"] == "keyword"
    assert fake_llm.calls == []


# ---------- LLM success and merge ----------

def test_llm_success_returns_llm_plan_with_method_metadata(llm_mode, llm_payload, sample_pdf_bytes):
    llm_mode.queue(llm_payload)
    result = _run(sample_pdf_bytes)
    plan = result.plan

    assert plan.extraction == "llm"
    info = plan.extraction_info
    assert (info.method, info.fallback, info.model) == ("llm", False, "claude-opus-5-5")
    assert info.sections["visits"] == "llm" and info.sections["billing"] == "none"
    assert len(plan.visits) == 3
    assert len(llm_mode.calls) == 1
    assert result.timings.attempts == 1


def test_merge_fills_sections_the_llm_left_empty(llm_mode, llm_payload, sample_pdf_bytes):
    llm_payload["safety"] = []  # the keyword extractor does find the SAE rule
    llm_payload["protocol"]["phase"] = None
    llm_mode.queue(llm_payload)
    plan = _run(sample_pdf_bytes).plan

    assert plan.safety, "keyword safety items should fill the gap"
    assert "Found by keyword" in plan.safety[0].notes  # item copied unchanged
    assert plan.safety[0].source_page == 1
    assert plan.extraction_info.sections["safety"] == "keyword"
    assert plan.protocol.phase == "Phase 2"  # header filled from the keyword header
    # LLM values are never overwritten by keyword ones.
    assert plan.protocol.title == "Synthetic Test Study of Drug X"


def test_merge_fills_empty_llm_staffing_with_its_review_flag(llm_mode, llm_payload, sample_pdf_bytes):
    llm_payload["staffing"] = []
    llm_mode.queue(llm_payload)
    plan = _run(sample_pdf_bytes).plan

    assert {s.role for s in plan.staffing} == {"Principal Investigator", "Study coordinator", "Pharmacist"}
    assert plan.extraction_info.sections["staffing"] == "keyword"
    # The LLM's "nothing found" flag no longer describes the section.
    assert plan.section_reviews.staffing.needs_review is False


def test_keyword_mode_flags_billing_and_a_missing_schedule(fake_llm, sample_pdf_bytes):
    plan = _run(sample_pdf_bytes).plan
    reviews = plan.section_reviews
    assert reviews.billing.needs_review and "clinical trial agreement" in reviews.billing.reason
    assert reviews.visits.needs_review and reviews.procedures.needs_review
    assert plan.extraction_info.sections["staffing"] == "keyword"


def test_merge_does_not_replace_llm_sections(llm_mode, llm_payload, sample_pdf_bytes):
    llm_mode.queue(llm_payload)
    plan = _run(sample_pdf_bytes).plan
    assert [s.event for s in plan.safety] == ["Serious adverse event"]
    assert [p.name for p in plan.procedures] == ["Informed consent", "Physical exam", "Blood draw"]


# ---------- fallback ----------

def test_llm_failure_returns_keyword_plan_with_visible_warning(llm_mode, sample_pdf_bytes, api_error):
    llm_mode.queue(api_error(401))
    plan = _run(sample_pdf_bytes).plan
    expected = KeywordExtractor().extract(pipeline.parse_pdf(sample_pdf_bytes, "sample_protocol.pdf"))

    assert plan.extraction == "keyword"
    info = plan.extraction_info
    assert info.fallback is True and info.reason == "invalid_key"
    assert "API key" in info.warning and "keyword" in info.warning
    # The keyword results are intact: same items, pages, confidence, notes.
    assert plan.safety == expected.safety and plan.procedures == expected.procedures


def test_bad_json_gets_its_own_message(llm_mode, sample_pdf_bytes):
    llm_mode.queue("not json at all")
    info = _run(sample_pdf_bytes).plan.extraction_info
    assert info.reason == "invalid_output"
    assert "couldn't read" in info.warning
    assert len(llm_mode.calls) == 1  # not retried


def test_bug_in_an_extractor_still_falls_back(llm_mode, sample_pdf_bytes):
    llm_mode.queue(RuntimeError("boom with protocol text Drug X"))
    info = _run(sample_pdf_bytes).plan.extraction_info
    assert info.fallback is True and info.reason == "unexpected"
    assert "Drug X" not in info.warning


# ---------- retries (issue #22) ----------

@pytest.mark.parametrize("kind", ["timeout", 429, 500, 529, "connection"])
def test_retryable_failure_is_retried_exactly_once_then_falls_back(llm_mode, sample_pdf_bytes, api_error, kind):
    llm_mode.queue(api_error(kind), api_error(kind), api_error(kind))  # a third call would be a bug
    result = _run(sample_pdf_bytes)
    assert len(llm_mode.calls) == 2
    assert result.plan.extraction_info.fallback is True
    assert result.timings.attempts == 2


@pytest.mark.parametrize("kind", [401, 403, 400, 404])
def test_non_retryable_failure_is_not_retried(llm_mode, sample_pdf_bytes, api_error, kind):
    llm_mode.queue(api_error(kind), api_error(kind))
    result = _run(sample_pdf_bytes)
    assert len(llm_mode.calls) == 1
    assert result.plan.extraction_info.fallback is True


def test_timeout_then_success_returns_the_llm_plan(llm_mode, llm_payload, sample_pdf_bytes, api_error):
    llm_mode.queue(api_error("timeout"), llm_payload)
    plan = _run(sample_pdf_bytes).plan
    assert plan.extraction == "llm" and plan.extraction_info.fallback is False
    assert len(llm_mode.calls) == 2


def test_retry_waits_with_bounded_backoff(llm_mode, llm_payload, sample_pdf_bytes, api_error, monkeypatch):
    waits = []
    monkeypatch.setattr(pipeline, "_sleep", waits.append)
    llm_mode.queue(api_error(429, headers={"retry-after": "600"}), llm_payload)
    _run(sample_pdf_bytes)
    assert waits == [pipeline.MAX_BACKOFF_SECONDS]  # a 10-minute hint is capped


def test_no_retry_when_the_deadline_is_too_close(llm_mode, sample_pdf_bytes, api_error):
    import time

    llm_mode.queue(api_error("timeout"), api_error("timeout"))
    _run(sample_pdf_bytes, deadline=time.monotonic() + 5.5)  # enough for one call, not the backoff + another
    assert len(llm_mode.calls) == 1


# ---------- nothing sensitive leaks (issues #22, #21, D1 privacy rule) ----------

def test_no_key_provider_text_or_protocol_text_in_response_or_logs(llm_mode, sample_pdf_bytes, api_error, caplog):
    body = {"error": {"message": f"key {SECRET} invalid; input was: Synthetic Test Study of Drug X"}}
    llm_mode.queue(api_error(500, body=body, message=f"{SECRET} upstream exploded"),
                   api_error(500, body=body, message=f"{SECRET} upstream exploded"))
    with caplog.at_level(logging.DEBUG):
        plan = _run(sample_pdf_bytes).plan

    assert "llm_fallback reason=provider_error status=500" in caplog.text
    info_text = plan.extraction_info.model_dump_json()
    for forbidden in (SECRET, "upstream exploded", "test-key-not-real"):
        assert forbidden not in caplog.text
        assert forbidden not in info_text
    assert "Synthetic Test Study" not in caplog.text  # no protocol text in logs


def test_timings_are_recorded_for_each_stage(llm_mode, llm_payload, sample_pdf_bytes):
    llm_mode.queue(llm_payload)
    t = _run(sample_pdf_bytes).timings
    assert t.ingest_ms > 0 and t.extract_ms > 0 and t.validate_ms > 0
    assert (t.pages, t.method, t.fallback) == (1, "llm", False)


# ---------- empty plans ----------

def _empty(payload):
    payload["visits"], payload["procedures"] = [], []
    return payload


# Enough text per page to pass the "readable text" check during ingest.
_LINE = "Participants attend clinic visits for physical exams, blood draws and ECGs.\n"
THREE_PAGES = [title + "\n" + _LINE * 12 for title in ("Protocol title page", "Schedule of activities", "Safety reporting")]


def test_empty_plan_is_retried_once_then_falls_back_with_its_own_message(llm_mode, llm_payload, make_pdf):
    # Seen with a real model: a valid call with the header filled in and no
    # visits or procedures. It must not be shown as a successful LLM plan.
    llm_mode.queue(_empty(llm_payload), _empty(llm_payload), llm_payload)  # a third call would be a bug
    result = _run(make_pdf(THREE_PAGES))
    info = result.plan.extraction_info
    assert len(llm_mode.calls) == 2
    assert info.fallback is True and info.reason == "empty_plan"
    assert "empty plan" in info.warning and "keyword" in info.warning


def test_empty_plan_then_full_plan_returns_the_llm_plan(llm_mode, llm_payload, make_pdf):
    import copy
    llm_mode.queue(_empty(copy.deepcopy(llm_payload)), llm_payload)
    plan = _run(make_pdf(THREE_PAGES)).plan
    assert plan.extraction == "llm" and plan.extraction_info.fallback is False
    assert [v.id for v in plan.visits] == ["V1", "V2", "V3"]


def test_short_document_may_have_an_empty_plan(llm_mode, llm_payload, sample_pdf_bytes):
    # One page can genuinely have no schedule; that is flagged, not retried.
    llm_mode.queue(_empty(llm_payload))
    plan = _run(sample_pdf_bytes).plan
    assert plan.extraction == "llm" and len(llm_mode.calls) == 1
    assert plan.section_reviews.visits.needs_review


def test_plan_with_only_procedures_is_not_empty(llm_mode, llm_payload, make_pdf):
    llm_payload["visits"] = []
    llm_mode.queue(llm_payload)
    plan = _run(make_pdf(THREE_PAGES)).plan
    assert plan.extraction == "llm" and len(llm_mode.calls) == 1
