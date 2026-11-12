"""The interface every extractor implements."""

from typing import Protocol, runtime_checkable

@runtime_checkable
class Extractor(Protocol):
    """Turns an uploaded protocol PDF into an operational-plan dict.

    The returned dict follows the plan JSON documented in README.md and
    models.OperationalPlan. Implementations raise extract.ExtractionError for
    problems with the document itself (unreadable, scanned, password-protected).
    """

    #: Short identifier, also used as the plan's "extraction" value.
    name: str

    def extract(self, pdf_bytes: bytes, filename: str) -> dict: ...