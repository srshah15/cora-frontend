"""The extractor interface, and the function that picks an implementation.

An "interface" here is a typing.Protocol: a description of what an extractor
must be able to do (have a name, turn a parsed PDF into a plan) without saying
how. main.py and pipeline.py are written against this description only. That
is what lets us swap keyword extraction for Claude, or Claude for some future
model, by changing an environment variable and without touching the API layer.

Implementations:
- KeywordExtractor (below): the rule-based baseline in extract.py.
- ClaudeExtractor (llm_extractor.py): LLM extraction through the Anthropic SDK.
"""

from __future__ import annotations

from typing import Optional, Protocol, runtime_checkable

from config import CLAUDE, Settings, get_settings
from extract import ParsedDocument, plan_from_parsed
from models import OperationalPlan


@runtime_checkable
class Extractor(Protocol):
    """Anything that can turn a parsed protocol into an operational plan."""

    # Recorded in the plan's "extraction" field so reviewers know the method.
    name: str

    def extract(self, parsed: ParsedDocument, *, deadline: Optional[float] = None) -> OperationalPlan:
        """Return a validated plan.

        deadline is a time.monotonic() value after which the caller has given
        up; slow extractors should stop waiting before it.
        """
        ...


class KeywordExtractor:
    """Rule-based extraction. Needs no API key and makes no network calls."""

    name = "keyword"

    def extract(self, parsed: ParsedDocument, *, deadline: Optional[float] = None) -> OperationalPlan:
        return OperationalPlan.model_validate(plan_from_parsed(parsed))


def get_extractor(settings: Optional[Settings] = None) -> Extractor:
    """Build the extractor named by CORA_EXTRACTOR.

    Used as a FastAPI dependency, so tests can substitute any object that
    satisfies the Extractor protocol.
    """
    settings = settings or get_settings()
    if settings.extractor == CLAUDE:
        # Imported here, not at the top, so keyword mode never loads the
        # Anthropic SDK and this module stays provider-neutral.
        from llm_extractor import ClaudeExtractor

        return ClaudeExtractor(settings)
    return KeywordExtractor()
