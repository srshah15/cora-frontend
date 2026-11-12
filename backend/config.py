"""Backend settings, read from environment variables.

Values come from the process environment, with backend/.env loaded once at
import time for local development. Real environment variables win over .env,
so a deployment never has its settings overridden by a stray file.

Settings are validated up front so a misconfigured server fails at startup with
a message that says exactly what to fix, instead of failing on the first upload.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Optional

from dotenv import load_dotenv

ENV_FILE = Path(__file__).with_name(".env")
load_dotenv(ENV_FILE, override=False)

EXTRACTORS = ("keyword", "llm")
DEFAULT_MODEL = "claude-sonnet-5-5"
DEFAULT_TIMEOUT = 60.0
DEFAULT_RETRIES = 2


class ConfigError(RuntimeError):
    """The backend is misconfigured: a required setting is missing or invalid."""


@dataclass(frozen=True)
class Settings:
    extractor: str = "keyword"
    llm_api_key: Optional[str] = None
    llm_model: str = DEFAULT_MODEL
    llm_timeout: float = DEFAULT_TIMEOUT
    llm_retries: int = DEFAULT_RETRIES


def _get(env: Mapping[str, str], name: str) -> Optional[str]:
    """The variable's value with whitespace stripped, or None if unset or blank."""
    value = env.get(name)
    if value is None:
        return None
    value = value.strip()
    return value or None


def _number(env, name, default, cast, minimum):
    raw = _get(env, name)
    if raw is None:
        return default
    try:
        value = cast(raw)
    except ValueError:
        raise ConfigError(f"{name} must be a number, got {raw!r}.") from None
    if value < minimum:
        raise ConfigError(f"{name} must be at least {minimum}, got {raw!r}.")
    return value


def load_settings(env: Optional[Mapping[str, str]] = None) -> Settings:
    """Build and validate Settings from ``env`` (defaults to os.environ)."""
    env = os.environ if env is None else env

    extractor = (_get(env, "EXTRACTOR") or "keyword").lower()
    if extractor not in EXTRACTORS:
        raise ConfigError(
            f"EXTRACTOR must be one of {', '.join(EXTRACTORS)}, got {extractor!r}."
        )

    settings = Settings(
        extractor=extractor,
        llm_api_key=_get(env, "LLM_API_KEY"),
        llm_model=_get(env, "LLM_MODEL") or DEFAULT_MODEL,
        llm_timeout=_number(env, "LLM_TIMEOUT", DEFAULT_TIMEOUT, float, 1),
        llm_retries=_number(env, "LLM_RETRIES", DEFAULT_RETRIES, int, 0),
    )

    if settings.extractor == "llm" and not settings.llm_api_key:
        raise ConfigError(
            "EXTRACTOR=llm needs LLM_API_KEY. Add it to backend/.env "
            "(copy backend/.env.example), or set EXTRACTOR=keyword to run without the LLM."
        )
    return settings