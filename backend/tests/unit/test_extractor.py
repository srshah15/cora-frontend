"""Tests for the extractor interface and how one is chosen (backend/extractor.py)."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import main
from config import ConfigError, get_settings
from extract import extract_plan, parse_pdf
from extractor import Extractor, KeywordExtractor, get_extractor
from models import OperationalPlan

BACKEND = Path(main.__file__).parent


def test_default_extractor_is_keyword():
    ex = get_extractor()
    assert isinstance(ex, KeywordExtractor)
    assert isinstance(ex, Extractor)  # satisfies the interface
    assert ex.name == "keyword"


def test_keyword_extractor_matches_extract_plan(sample_pdf_bytes):
    # The refactor must not change keyword output.
    parsed = parse_pdf(sample_pdf_bytes, "sample_protocol.pdf")
    expected = OperationalPlan.model_validate(extract_plan(sample_pdf_bytes, "sample_protocol.pdf"))
    assert KeywordExtractor().extract(parsed) == expected


def test_parse_pdf_keeps_page_order(sample_pdf_bytes):
    parsed = parse_pdf(sample_pdf_bytes, "sample_protocol.pdf")
    assert parsed.filename == "sample_protocol.pdf"
    assert len(parsed.pages) == 1
    assert "NCT00000000" in parsed.pages[0]


def test_claude_extractor_chosen_by_env(monkeypatch):
    monkeypatch.setenv("EXTRACTOR", "llm")
    monkeypatch.setenv("LLM_API_KEY", "test-key")
    monkeypatch.setenv("LLM_MODEL", "some-model")
    monkeypatch.setenv("LLM_TIMEOUT", "7")

    ex = get_extractor()
    assert isinstance(ex, Extractor)
    assert ex.name == "llm"
    assert ex.model == "some-model"
    # Building the client opens no connection, so the network guard stays quiet.
    assert ex.client.api_key == "test-key"
    assert ex.client.timeout == 7
    assert ex.client.max_retries == 0  # the pipeline owns retries (issue #22)


def test_claude_client_requires_a_key():
    from dataclasses import replace

    from llm_extractor import make_client

    settings = replace(get_settings(), extractor="llm", anthropic_api_key=None)
    with pytest.raises(ConfigError, match="LLM_API_KEY"):
        make_client(settings)


def test_server_refuses_to_start_in_llm_mode_without_key(monkeypatch):
    monkeypatch.setenv("EXTRACTOR", "llm")
    with pytest.raises(ConfigError, match="LLM_API_KEY"):
        with TestClient(main.app):
            pass


def test_route_uses_whatever_extractor_it_is_given(client, sample_pdf_bytes):
    """The route depends on the interface: any object with name + extract works."""

    class StubExtractor:
        name = "stub"

        def extract(self, parsed, *, deadline=None):
            return OperationalPlan(protocol={"title": "From the stub", "pages": len(parsed.pages)})

    main.app.dependency_overrides[get_extractor] = StubExtractor
    try:
        r = client.post(
            "/api/protocols",
            files={"file": ("sample_protocol.pdf", sample_pdf_bytes, "application/pdf")},
        )
    finally:
        main.app.dependency_overrides.clear()

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["extraction"] == "stub"
    assert body["protocol"]["title"] == "From the stub"
    assert body["extraction_info"]["method"] == "stub"


def test_only_llm_extractor_imports_the_anthropic_sdk():
    """The API layer and the interface stay provider-neutral."""
    for name in ("main.py", "extractor.py", "extract.py", "config.py"):
        source = (BACKEND / name).read_text()
        assert "import anthropic" not in source, name
        assert "from anthropic" not in source, name
