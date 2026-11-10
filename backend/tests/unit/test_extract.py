"""Unit tests for PDF text extraction (backend/extract.py) and test isolation."""

import socket

import pytest

from extract import ExtractionError, read_pdf


def test_read_pdf_finds_known_text(sample_pdf_bytes):
    _doc, pages, _flags = read_pdf(sample_pdf_bytes)
    assert len(pages) == 1
    assert "Synthetic Test Study of Drug X" in pages[0]
    assert "NCT00000000" in pages[0]


def test_read_pdf_rejects_non_pdf_bytes():
    with pytest.raises(ExtractionError, match="couldn't be opened as a PDF"):
        read_pdf(b"not a pdf")


def test_network_guard_blocks_connections():
    with pytest.raises(RuntimeError, match="Network access attempted"):
        socket.create_connection(("example.com", 443), timeout=1)
    with pytest.raises(RuntimeError, match="Network access attempted"):
        socket.socket().connect(("93.184.216.34", 443))
