"""The upload route goes through the Extractor interface, chosen by EXTRACTOR."""

import pytest
from fastapi.testclient import TestClient

import main
from config import ConfigError
from extractors import KeywordExtractor
from extractors.claude import ClaudeExtractor


class FakeExtractor:
    name = "fake"

    def __init__(self):
        self.calls = []

    def extract(self, pdf_bytes, filename):
        self.calls.append((pdf_bytes, filename))
        return {"id": "fake", "extraction": "fake", "protocol": {"title": filename}}


def _upload(client, data=b"%PDF-1.4 fake"):
    return client.post("/api/protocols", files={"file": ("p.pdf", data, "application/pdf")})


def test_route_uses_whatever_extractor_is_injected(client):
    fake = FakeExtractor()
    main.app.dependency_overrides[main.get_extractor] = lambda: fake
    try:
        r = _upload(client)
    finally:
        main.app.dependency_overrides.clear()
    assert r.status_code == 200
    assert r.json()["extraction"] == "fake"
    assert fake.calls == [(b"%PDF-1.4 fake", "p.pdf")]


def test_default_startup_uses_keyword_extractor(client):
    assert isinstance(main.app.state.extractor, KeywordExtractor)


def test_llm_startup_without_key_fails_with_config_error(monkeypatch):
    monkeypatch.setenv("EXTRACTOR", "llm")
    with pytest.raises(ConfigError, match="LLM_API_KEY"):
        with TestClient(main.app):
            pass


def test_llm_mode_returns_501_until_issue_18(monkeypatch):
    monkeypatch.setenv("EXTRACTOR", "llm")
    monkeypatch.setenv("LLM_API_KEY", "sk-test-not-real")
    with TestClient(main.app) as c:
        assert isinstance(main.app.state.extractor, ClaudeExtractor)
        r = _upload(c)
    assert r.status_code == 501
    assert "EXTRACTOR=keyword" in r.json()["detail"]