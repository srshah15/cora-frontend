"""The rule-based extractor in extract.py, behind the Extractor interface."""

from extract import extract_plan

class KeywordExtractor:
    name = "keyword"

    def extract(self, pdf_bytes: bytes, filename: str) -> dict:
        return extract_plan(pdf_bytes, filename)