"""Unit tests for environment-based configuration (backend/config.py)."""

import pytest

import config
from config import ConfigError, get_settings


def test_defaults_need_no_environment():
    s = get_settings()
    assert s.extractor == "keyword"
    assert s.anthropic_api_key is None
    assert s.llm_model == config.DEFAULT_LLM_MODEL
    assert s.llm_timeout_seconds == config.DEFAULT_LLM_TIMEOUT_SECONDS


def test_environment_overrides(monkeypatch):
    monkeypatch.setenv("CORA_EXTRACTOR", "Claude")  # case-insensitive
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setenv("CORA_LLM_MODEL", "some-other-model")
    monkeypatch.setenv("CORA_LLM_TIMEOUT_SECONDS", "12.5")

    s = get_settings()
    assert s.extractor == "claude"
    assert s.anthropic_api_key == "test-key"
    assert s.llm_model == "some-other-model"
    assert s.llm_timeout_seconds == 12.5


def test_unknown_extractor_is_a_config_error(monkeypatch):
    monkeypatch.setenv("CORA_EXTRACTOR", "gpt")
    with pytest.raises(ConfigError, match="CORA_EXTRACTOR"):
        get_settings()


@pytest.mark.parametrize("value", ["abc", "0", "-5"])
def test_bad_timeout_is_a_config_error(monkeypatch, value):
    monkeypatch.setenv("CORA_LLM_TIMEOUT_SECONDS", value)
    with pytest.raises(ConfigError, match="CORA_LLM_TIMEOUT_SECONDS"):
        get_settings()


@pytest.mark.parametrize("key", [None, "", "   "])
def test_llm_mode_without_key_is_a_clear_config_error(monkeypatch, key):
    monkeypatch.setenv("CORA_EXTRACTOR", "claude")
    if key is not None:
        # .env.example's "ANTHROPIC_API_KEY=" loads as an empty string.
        monkeypatch.setenv("ANTHROPIC_API_KEY", key)

    with pytest.raises(ConfigError) as err:
        get_settings()
    message = str(err.value)
    assert "ANTHROPIC_API_KEY" in message  # says what is missing
    assert ".env" in message               # says where to fix it


def test_keyword_mode_ignores_a_missing_key():
    # No key and no CORA_EXTRACTOR: must not raise.
    assert get_settings().extractor == "keyword"


def test_settings_repr_never_shows_the_key(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-very-secret")
    text = repr(get_settings())
    assert "sk-ant-very-secret" not in text
    assert "<set>" in text
