"""Claude API client for LLM extraction.

This module owns everything Anthropic-specific. The prompts that turn protocol
text into each plan section should call ``complete()`` so model, timeout, and 
retries stay configured in one place.
"""

from __future__ import annotations

from typing import Optional

import anthropic

from config import Settings


class ClaudeExtractor:
    name = "llm"

    def __init__(self, settings: Settings, client: Optional[anthropic.Anthropic] = None):
        self.model = settings.llm_model
        self.timeout_seconds = settings.llm_timeout
        # Tests pass a fake client; the real one is only built with a key.
        self.client = client or anthropic.Anthropic(
            api_key=settings.llm_api_key,
            timeout=settings.llm_timeout,
            max_retries=settings.llm_retries,
        )

    def complete(self, system: str, user: str, max_tokens: int = 8000) -> str:
        """Send one prompt to Claude and return the text of its reply."""
        message = self.client.messages.create(
            model=self.model,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        return "".join(block.text for block in message.content if block.type == "text")

    def extract(self, pdf_bytes: bytes, filename: str) -> dict:
        raise NotImplementedError(
            "LLM extraction isn't implemented yet. Set EXTRACTOR=keyword in backend/.env for now."
        )