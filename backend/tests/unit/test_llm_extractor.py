"""Unit tests for the Claude extractor (backend/llm_extractor.py), with a mocked LLM.

Covers the four response kinds from issue #31: valid, partially valid,
malformed JSON and schema-invalid, plus the "don't invent" checks from #18.
"""

import time
from types import SimpleNamespace

import pytest

import llm_extractor
from config import get_settings
from extract import parse_pdf
from llm_extractor import ClaudeExtractor, LLMError, build_prompt, map_error
from models import OperationalPlan


@pytest.fixture
def parsed(sample_pdf_bytes):
    return parse_pdf(sample_pdf_bytes, "sample_protocol.pdf")


@pytest.fixture
def extractor(llm_mode):
    return ClaudeExtractor(get_settings())


# ---------- valid ----------

def test_valid_response_becomes_a_validated_plan(extractor, llm_mode, llm_payload, parsed):
    llm_mode.queue(llm_payload)
    plan = extractor.extract(parsed)

    assert isinstance(plan, OperationalPlan)
    assert plan.extraction == "llm"
    assert [v.id for v in plan.visits] == ["V1", "V2", "V3"]
    v3 = plan.visits[2]
    assert (v3.name, v3.day, v3.window, v3.source_page, v3.confidence) == ("Follow-up", "Week 4", "+/- 3 days", 1, 0.9)
    assert plan.procedures[1].visits == ["V1", "V2"]
    assert [s.role for s in plan.staffing] == ["Principal Investigator", "Study Coordinator"]
    assert plan.safety[0].timeline == "Within 24 hours"
    # Low confidence from the model is kept, with its note, so it gets flagged.
    assert plan.procedures[2].confidence == 0.6
    assert "analytes" in plan.procedures[2].notes
    # Nothing was wrong, so no section is flagged.
    assert not plan.section_reviews.procedures.needs_review


def test_page_count_and_registry_id_come_from_the_pdf_not_the_model(extractor, llm_mode, llm_payload, parsed):
    llm_mode.queue(llm_payload)
    plan = extractor.extract(parsed)
    assert plan.protocol.pages == 1
    assert plan.protocol.registry_id == "NCT00000000"  # found by regex in the text


def test_request_sends_page_numbered_text_and_the_schema(extractor, llm_mode, llm_payload, parsed):
    llm_mode.queue(llm_payload)
    extractor.extract(parsed)

    call = llm_mode.calls[0]
    prompt = call["messages"][0]["content"]
    assert '<page n="1">' in prompt and "Synthetic Test Study of Drug X" in prompt
    assert call["tools"] == [llm_extractor.PLAN_TOOL]
    assert call["tool_choice"] == {"type": "auto"}  # a forced tool_choice is rejected by current models
    assert call["model"] == "claude-opus-5-5"
    assert call["output_config"] == {"effort": "medium"}
    assert "Never fill a gap" in call["system"]  # the no-invention rule
    assert llm_mode.options[0]["timeout"] == 50.0


def test_plan_schema_is_sent_as_a_non_strict_tool(extractor, llm_mode, llm_payload, parsed):
    # Regression: LLMPlan sent as a structured-output schema (output_format) or
    # a strict tool is compiled into a grammar, and the API rejects it as too
    # large on every model, so every upload silently fell back to keywords.
    llm_mode.queue(llm_payload)
    extractor.extract(parsed)

    call = llm_mode.calls[0]
    assert "output_format" not in call
    assert "format" not in call["output_config"]
    tool = call["tools"][0]
    assert not tool.get("strict")
    assert tool["input_schema"] == llm_extractor.LLMPlan.model_json_schema()


def test_only_the_submit_plan_tool_input_is_used(extractor, llm_mode, llm_payload, parsed, monkeypatch):
    # A text block before the tool call is ignored; the plan comes from the tool.
    real_create = llm_mode.create

    def with_preamble(**kwargs):
        response = real_create(**kwargs)
        response.content.insert(0, SimpleNamespace(type="text", text="Here is the plan."))
        return response

    monkeypatch.setattr(llm_mode, "create", with_preamble)
    llm_mode.queue(llm_payload)
    assert [v.id for v in extractor.extract(parsed).visits] == ["V1", "V2", "V3"]


def test_build_prompt_numbers_pages_from_one():
    prompt = build_prompt(["first", "second"])
    assert prompt.index('<page n="1">\nfirst') < prompt.index('<page n="2">\nsecond')


def test_stretch_categories_are_extracted(extractor, llm_mode, llm_payload, parsed):
    llm_payload["billing"] = [{"item": "ECG", "designation": "Sponsor", "visits": ["V2"],
                               "source_page": 1, "confidence": 0.8, "notes": None}]
    llm_payload["equipment"] = [{"item": "ECG machine", "purpose": "12-lead ECG",
                                 "source_page": 1, "confidence": 0.8, "notes": None}]
    llm_payload["technology"] = [{"system": "EDC", "purpose": "Data entry",
                                  "source_page": 1, "confidence": 0.8, "notes": None}]
    llm_payload["pharmacy_involved"] = True
    llm_payload["pharmacy_items"] = [{"item": "Store at 2-8 C", "source_page": 1, "confidence": 0.8, "notes": None}]
    llm_mode.queue(llm_payload)

    plan = extractor.extract(parsed)
    assert plan.billing[0].designation == "Sponsor" and plan.billing[0].visits == ["V2"]
    assert plan.equipment[0].source_page == 1
    assert plan.technology[0].system == "EDC"
    assert plan.pharmacy.involved is True and plan.pharmacy.items[0].item == "Store at 2-8 C"


def test_unknown_pharmacy_status_is_not_reported_as_not_involved(extractor, llm_mode, llm_payload, parsed):
    llm_mode.queue(llm_payload)  # pharmacy_involved is null
    assert extractor.extract(parsed).pharmacy is None


# ---------- the code-side "don't invent, flag uncertainty" checks ----------

def test_page_that_does_not_exist_is_cleared_and_item_flagged(extractor, llm_mode, llm_payload, parsed):
    llm_payload["procedures"][0]["source_page"] = 99  # the PDF has 1 page
    llm_mode.queue(llm_payload)
    proc = extractor.extract(parsed).procedures[0]
    assert proc.source_page is None
    assert proc.confidence < 0.7
    assert "doesn't exist" in proc.notes


def test_item_without_source_page_is_capped_below_threshold(extractor, llm_mode, llm_payload, parsed):
    llm_payload["staffing"][0].update(source_page=None, confidence=0.99)
    llm_mode.queue(llm_payload)
    role = extractor.extract(parsed).staffing[0]
    assert role.confidence == 0.69
    assert "No source page" in role.notes


@pytest.mark.parametrize("bad", [None, 1.7, -0.2])
def test_missing_or_out_of_range_confidence_is_flagged(extractor, llm_mode, llm_payload, parsed, bad):
    llm_payload["safety"][0]["confidence"] = bad
    llm_mode.queue(llm_payload)
    item = extractor.extract(parsed).safety[0]
    assert item.confidence == 0.5
    assert "No usable confidence" in item.notes


def test_visit_tag_not_in_schedule_is_removed_with_a_note(extractor, llm_mode, llm_payload, parsed):
    llm_payload["procedures"][0]["visits"] = ["V1", "V9"]
    llm_mode.queue(llm_payload)
    proc = extractor.extract(parsed).procedures[0]
    assert proc.visits == ["V1"]
    assert "V9" in proc.notes
    assert proc.confidence < 0.7


def test_empty_minimum_success_sections_are_flagged(extractor, llm_mode, llm_payload, parsed):
    llm_payload.update(visits=[], staffing=[])
    for p in llm_payload["procedures"]:
        p["visits"] = []
    llm_mode.queue(llm_payload)
    plan = extractor.extract(parsed)
    assert plan.visits == [] and plan.staffing == []
    assert plan.section_reviews.visits.needs_review
    assert "No staffing were found" in plan.section_reviews.staffing.reason


def test_low_confidence_visits_flag_the_visits_section(extractor, llm_mode, llm_payload, parsed):
    llm_payload["visits"][1].update(confidence=0.4, notes="Timing unclear.")
    llm_mode.queue(llm_payload)
    plan = extractor.extract(parsed)
    assert plan.section_reviews.visits.needs_review
    assert "V2" in plan.section_reviews.visits.reason


def test_fte_is_not_invented(extractor, llm_mode, llm_payload, parsed):
    llm_mode.queue(llm_payload)
    assert all(s.fte is None for s in extractor.extract(parsed).staffing)


# ---------- partially valid ----------

def test_partial_response_keeps_good_items_and_flags_the_section(extractor, llm_mode, llm_payload, parsed):
    llm_payload["staffing"].append(
        {"role": "Research Pharmacist", "fte": -1.0, "responsibilities": None, "qualifications": None,
         "source_page": 1, "confidence": 0.9, "notes": None}  # negative FTE is invalid
    )
    llm_payload["procedures"].append(
        {"name": "  ", "category": None, "visits": [], "source_page": 1, "confidence": 0.9, "notes": None}
    )
    llm_payload["visits"].append(dict(llm_payload["visits"][0]))  # duplicate id V1
    llm_mode.queue(llm_payload)

    plan = extractor.extract(parsed)
    assert [s.role for s in plan.staffing] == ["Principal Investigator", "Study Coordinator"]
    assert "1 item(s)" in plan.section_reviews.staffing.reason
    assert len(plan.procedures) == 3
    assert plan.section_reviews.procedures.needs_review
    assert [v.id for v in plan.visits] == ["V1", "V2", "V3"]
    assert "shared the id V1" in plan.section_reviews.visits.reason


# ---------- no plan, or a plan that doesn't fit the schema ----------

def test_text_reply_without_the_tool_call_is_invalid_output(extractor, llm_mode, parsed):
    llm_mode.queue('{"protocol": {"title": "cut off')
    with pytest.raises(LLMError) as err:
        extractor.extract(parsed)
    assert err.value.reason == "invalid_output"
    assert err.value.retryable is False


def test_schema_invalid_json_is_invalid_output(extractor, llm_mode, llm_payload, parsed):
    del llm_payload["visits"]            # a required key is missing
    llm_payload["procedures"] = "none"   # wrong type
    llm_mode.queue(llm_payload)
    with pytest.raises(LLMError) as err:
        extractor.extract(parsed)
    assert err.value.reason == "invalid_output"


@pytest.mark.parametrize("stop, reason", [("refusal", "refused"), ("max_tokens", "truncated")])
def test_refusal_and_truncation_are_failures(extractor, llm_mode, parsed, stop, reason):
    llm_mode.queue(("stop", stop))
    with pytest.raises(LLMError) as err:
        extractor.extract(parsed)
    assert err.value.reason == reason


# ---------- limits ----------

def test_over_long_input_fails_clearly_instead_of_being_truncated(extractor, llm_mode, parsed, monkeypatch):
    monkeypatch.setattr(llm_extractor, "MAX_INPUT_CHARS", 10)
    with pytest.raises(LLMError) as err:
        extractor.extract(parsed)
    assert err.value.reason == "too_long"
    assert llm_mode.calls == []  # nothing was sent


def test_no_call_when_the_deadline_has_nearly_passed(extractor, llm_mode, parsed):
    with pytest.raises(LLMError) as err:
        extractor.extract(parsed, deadline=time.monotonic() + 1)
    assert err.value.reason == "deadline"
    assert llm_mode.calls == []


def test_call_timeout_shrinks_to_fit_the_deadline(extractor, llm_mode, llm_payload, parsed):
    llm_mode.queue(llm_payload)
    extractor.extract(parsed, deadline=time.monotonic() + 20)
    assert 15 < llm_mode.options[0]["timeout"] <= 20


# ---------- error mapping (issue #22) ----------

@pytest.mark.parametrize(
    "kind, reason, retryable",
    [
        ("timeout", "timeout", True),
        ("connection", "connection", True),
        (429, "rate_limited", True),
        (500, "provider_error", True),
        (529, "provider_error", True),
        (401, "invalid_key", False),
        (403, "invalid_key", False),
        (400, "rejected", False),
        (404, "rejected", False),
    ],
)
def test_sdk_errors_map_to_reason_codes(api_error, kind, reason, retryable):
    err = map_error(api_error(kind))
    assert (err.reason, err.retryable) == (reason, retryable)
    assert err.user_message  # every reason has a sentence for the user


def test_rate_limit_keeps_the_retry_after_header(api_error):
    assert map_error(api_error(429, headers={"retry-after": "3"})).retry_after == 3.0


def test_llm_error_never_carries_provider_text(extractor, llm_mode, parsed, api_error):
    secret_body = {"error": {"message": "invalid x-api-key sk-ant-LEAKED-KEY for request with text 'Drug X'"}}
    llm_mode.queue(api_error(401, body=secret_body, message="sk-ant-LEAKED-KEY rejected"))
    with pytest.raises(LLMError) as err:
        extractor.extract(parsed)
    text = f"{err.value} {err.value.user_message} {err.value.__cause__} {err.value.args}"
    assert "LEAKED" not in text and "Drug X" not in text
    assert err.value.__cause__ is None  # the SDK exception is not chained
