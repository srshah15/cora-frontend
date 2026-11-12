"""Backend configuration, read from environment variables.

Why a separate module: every setting lives in one place, and nothing else in
the backend reads os.environ directly. Values come from the real environment
or from backend/.env (loaded once in main.py with python-dotenv).

Settings are read when get_settings() is *called*, not when this module is
imported. That matters for tests: conftest.py removes keys and CORA_* variables
before each test, and a value captured at import time would ignore that.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional

KEYWORD = "keyword"
LLM = "llm"  # the Claude extractor (llm_extractor.py)
EXTRACTORS = (KEYWORD, LLM)

# Keyword stays the default so the app works with no key and no network.
# LLM extraction is something an administrator opts into.
DEFAULT_EXTRACTOR = KEYWORD
DEFAULT_LLM_MODEL = "claude-opus-5-5"
# A full plan for a 20-page protocol takes ~45-50 s even on the fastest model,
# so 50 s timed out about half the time. 100 s still fits inside the 120 s
# request limit (the retry is skipped when it would not fit).
DEFAULT_LLM_TIMEOUT_SECONDS = 100.0
# How hard the model thinks: low | medium | high | xhigh | max. Higher is
# slower and costs more; medium balances accuracy against the 60 s target.
DEFAULT_LLM_EFFORT = "medium"
EFFORTS = ("low", "medium", "high", "xhigh", "max")
# Typical protocols are 50-150 pages. Longer files fail with a clear message.
DEFAULT_MAX_PAGES = 150
# Upper bound for one upload request, end to end.
DEFAULT_REQUEST_TIMEOUT_SECONDS = 120.0
# OCR takes a second or more per page, so scanned pages are capped separately.
DEFAULT_MAX_OCR_PAGES = 50
DEFAULT_CORS_ORIGINS = (
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://[::1]:5173",
)


class ConfigError(Exception):
    """The server is misconfigured. The message says which variable to fix.

    Messages must never include a secret's value, only the variable's name.
    """


@dataclass(frozen=True)
class Settings:
    extractor: str
    anthropic_api_key: Optional[str]
    llm_model: str
    llm_timeout_seconds: float
    llm_effort: str = DEFAULT_LLM_EFFORT
    max_pages: int = DEFAULT_MAX_PAGES
    request_timeout_seconds: float = DEFAULT_REQUEST_TIMEOUT_SECONDS
    max_ocr_pages: int = DEFAULT_MAX_OCR_PAGES

    def __repr__(self) -> str:
        # The default dataclass repr would print the key, and reprs end up in
        # logs and tracebacks. Show only whether a key is present.
        return (
            f"Settings(extractor={self.extractor!r}, "
            f"anthropic_api_key={'<set>' if self.anthropic_api_key else '<missing>'}, "
            f"llm_model={self.llm_model!r}, llm_timeout_seconds={self.llm_timeout_seconds!r})"
        )


def _env(name: str) -> Optional[str]:
    # .env.example ships lines like "LLM_API_KEY =", which load as an
    # empty string. Treat empty and whitespace-only the same as not set.
    value = os.environ.get(name, "").strip()
    return value or None


def _positive(name: str, default, cast, what: str):
    """Read a positive number from the environment, or raise a ConfigError."""
    raw = _env(name)
    if raw is None:
        return default
    try:
        value = cast(raw)
    except ValueError:
        value = 0
    if value <= 0:
        raise ConfigError(f"{name} must be a positive {what}, got {raw!r}.")
    return value


def cors_origins() -> list:
    """Browser origins allowed to call the API.

    CORS_ORIGINS is a comma-separated list, e.g. the deployed frontend's URL.
    The local dev origins are always allowed.
    """
    extra = [o.strip().rstrip("/") for o in (_env("CORS_ORIGINS") or "").split(",") if o.strip()]
    return list(dict.fromkeys([*DEFAULT_CORS_ORIGINS, *extra]))


def get_settings() -> Settings:
    """Read and validate settings from the environment."""
    extractor = (_env("EXTRACTOR") or DEFAULT_EXTRACTOR).lower()
    if extractor not in EXTRACTORS:
        raise ConfigError(
            f"EXTRACTOR is set to {extractor!r}, which isn't a known extractor. "
            f"Use one of: {', '.join(EXTRACTORS)}."
        )

    effort = (_env("CORA_LLM_EFFORT") or DEFAULT_LLM_EFFORT).lower()
    if effort not in EFFORTS:
        raise ConfigError(
            f"CORA_LLM_EFFORT is set to {effort!r}. Use one of: {', '.join(EFFORTS)}."
        )

    settings = Settings(
        extractor=extractor,
        anthropic_api_key=_env("LLM_API_KEY"),
        llm_model=_env("LLM_MODEL") or DEFAULT_LLM_MODEL,
        llm_timeout_seconds=_positive("LLM_TIMEOUT", DEFAULT_LLM_TIMEOUT_SECONDS, float, "number of seconds"),
        llm_effort=effort,
        max_pages=_positive("CORA_MAX_PAGES", DEFAULT_MAX_PAGES, int, "whole number of pages"),
        request_timeout_seconds=_positive(
            "CORA_REQUEST_TIMEOUT_SECONDS", DEFAULT_REQUEST_TIMEOUT_SECONDS, float, "number of seconds"
        ),
        max_ocr_pages=_positive("CORA_MAX_OCR_PAGES", DEFAULT_MAX_OCR_PAGES, int, "whole number of pages"),
    )

    if settings.extractor == LLM and not settings.anthropic_api_key:
        raise ConfigError(
            "EXTRACTOR is 'llm' but LLM_API_KEY is not set. "
            "Add your key to backend/.env (copy backend/.env.example), "
            "or set EXTRACTOR=keyword to run without the LLM."
        )
    return settings
