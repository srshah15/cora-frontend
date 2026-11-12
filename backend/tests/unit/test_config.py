"""Settings loading and validation (backend/config.py)."""

import pytest

from config import DEFAULT_MODEL, ConfigError, load_settings


def test_defaults_to_keyword_with_no_env():
    s = load_settings({})
    assert s.extractor == "keyword"
    assert s.llm_api_key is None
    assert s.llm_model == DEFAULT_MODEL
    assert s.llm_timeout == 60.0
    assert s.llm_retries == 2


def test_llm_mode_reads_key_model_timeout_and_retries():
    s = load_settings({
        "EXTRACTOR": "LLM",
        "LLM_API_KEY": " sk-test ",
        "LLM_MODEL": "claude-haiku-5-5",
        "LLM_TIMEOUT": "90",
        "LLM_RETRIES": "0",
    })
    assert s.extractor == "llm"
    assert s.llm_api_key == "sk-test"
    assert s.llm_model == "claude-haiku-5-5"
    assert s.llm_timeout == 90.0
    assert s.llm_retries == 0


@pytest.mark.parametrize("key", [None, "", "   "])
def test_llm_mode_without_key_is_a_clear_config_error(key):
    env = {"EXTRACTOR": "llm"}
    if key is not None:
        env["LLM_API_KEY"] = key
    with pytest.raises(ConfigError, match="LLM_API_KEY"):
        load_settings(env)


def test_keyword_mode_does_not_need_a_key():
    assert load_settings({"EXTRACTOR": "keyword"}).extractor == "keyword"


def test_unknown_extractor_rejected():
    with pytest.raises(ConfigError, match="EXTRACTOR must be one of"):
        load_settings({"EXTRACTOR": "gpt"})


@pytest.mark.parametrize("value", ["soon", "0", "-5"])
def test_bad_timeout_rejected(value):
    with pytest.raises(ConfigError, match="LLM_TIMEOUT"):
        load_settings({"LLM_TIMEOUT": value})


def test_blank_model_falls_back_to_default():
    assert load_settings({"LLM_MODEL": "  "}).llm_model == DEFAULT_MODEL