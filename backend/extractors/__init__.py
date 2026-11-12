"""Protocol extractors and the factory that picks one from settings.

The API layer (main.py) only knows about the Extractor interface. Adding a new
provider means adding a class here and a branch in build_extractor. main.py does not change.
"""

from config import ConfigError, Settings

from .base import Extractor
from .keyword import KeywordExtractor

__all__ = ["Extractor", "KeywordExtractor", "build_extractor"]


def build_extractor(settings: Settings) -> Extractor:
    if settings.extractor == "keyword":
        return KeywordExtractor()
    if settings.extractor == "llm":
        # Imported here so keyword mode never touches the Anthropic SDK.
        from .claude import ClaudeExtractor

        return ClaudeExtractor(settings)
    raise ConfigError(f"Unknown extractor {settings.extractor!r}.")