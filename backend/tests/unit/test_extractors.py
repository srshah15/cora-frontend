"""Extractor factory and the Claude client wrapper. No network: the client is faked."""

from types import SimpleNamespace

import pytest

from config import Settings
from extractors import Extractor, KeywordExtractor, build_extractor
from extractors.claude import ClaudeExtractor


def test_keyword_settings_build_keyword_extractor():
    ex = build_extractor(Settings(extractor="keyword"))
    assert isinstance(ex, KeywordExtractor)
    assert isinstance(ex, Extractor)


def test_llm_settings_build_configured_claude_extractor():
    settings = Settings(
        extractor="llm", llm_api_key="sk-test",
        llm_model="claude-haiku-5-5", llm_timeout=45, llm_retries=1,
    )
    ex = build_extractor(settings)
    assert isinstance(ex, ClaudeExtractor)
    assert isinstance(ex, Extractor)
    assert ex.model == "claude-haiku-5-5"
    assert ex.client.timeout == 45
    assert ex.client.max_retries == 1


class FakeMessages:
    def __init__(self):
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(content=[
            SimpleNamespace(type="thinking", thinking="..."),
            SimpleNamespace(type="text", text='{"visits": '),
            SimpleNamespace(type="text", text="[]}"),
        ])


def test_complete_sends_configured_model_and_returns_text():
    fake = SimpleNamespace(messages=FakeMessages())
    ex = ClaudeExtractor(Settings(extractor="llm", llm_model="claude-sonnet-5-5"), client=fake)

    out = ex.complete("You extract visit schedules.", "Protocol text", max_tokens=100)

    assert out == '{"visits": []}'
    call = fake.messages.calls[0]
    assert call["model"] == "claude-sonnet-5-5"
    assert call["max_tokens"] == 100
    assert call["system"] == "You extract visit schedules."
    assert call["messages"] == [{"role": "user", "content": "Protocol text"}]


def test_llm_extract_is_not_implemented_yet():
    ex = ClaudeExtractor(Settings(extractor="llm"), client=SimpleNamespace())
    with pytest.raises(NotImplementedError, match="LLM extraction isn't implemented yet. Set EXTRACTOR=keyword in backend/.env for now."):
        ex.extract(b"%PDF", "x.pdf")