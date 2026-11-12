"""OCR fallback for scanned PDFs (issue #23).

Tests that need the real Tesseract are skipped when it isn't installed
(`brew install tesseract` on macOS). The rest replace the OCR step with a
stub, so the page-handling logic is always tested.
"""

from pathlib import Path

import pymupdf
import pytest

import extract
from extract import ExtractionError, ProtocolTooLongError, ocr_available, parse_pdf, read_pdf

SCANNED = Path(__file__).parent.parent / "fixtures" / "scanned_protocol.pdf"

needs_tesseract = pytest.mark.skipif(not ocr_available(), reason="Tesseract is not installed")

TEXT_PAGE = "This page has a normal text layer with plenty of selectable characters on it. " * 6


def _image_page(doc):
    """Append a page that is only a picture (no text layer), like a scan."""
    src = pymupdf.open()
    p = src.new_page()
    p.insert_text((50, 72), "SCANNED PAGE CONTENT", fontsize=20)
    pix = p.get_pixmap(dpi=100, colorspace=pymupdf.csGRAY)
    src.close()
    page = doc.new_page()
    page.insert_image(page.rect, pixmap=pix)


def _mixed_pdf() -> bytes:
    """Page 1 text, page 2 scanned, page 3 text."""
    doc = pymupdf.open()
    doc.new_page().insert_textbox(pymupdf.Rect(50, 50, 550, 750), "FIRST " + TEXT_PAGE, fontsize=10)
    _image_page(doc)
    doc.new_page().insert_textbox(pymupdf.Rect(50, 50, 550, 750), "THIRD " + TEXT_PAGE, fontsize=10)
    data = doc.tobytes()
    doc.close()
    return data


@pytest.fixture
def stub_ocr(monkeypatch):
    """Pretend Tesseract is installed; record which pages were sent to OCR."""
    seen = []

    def fake_ocr(page):
        seen.append(page.number + 1)
        return "OCR TEXT FOR PAGE %d. " % (page.number + 1) + "recognised words " * 30

    monkeypatch.setattr(extract, "ocr_available", lambda: True)
    monkeypatch.setattr(extract, "_ocr_page", fake_ocr)
    return seen


# ---------- always run (OCR step stubbed) ----------

def test_text_native_pdf_never_runs_ocr(sample_pdf_bytes, stub_ocr):
    parsed = parse_pdf(sample_pdf_bytes, "sample_protocol.pdf")
    assert stub_ocr == []
    assert parsed.ocr_pages == 0
    assert "Synthetic Test Study of Drug X" in parsed.pages[0]  # exact text layer kept


def test_only_thin_pages_are_ocrd_and_page_numbers_are_preserved(stub_ocr):
    parsed = parse_pdf(_mixed_pdf(), "mixed.pdf")
    assert stub_ocr == [2]                      # only the scanned page
    assert parsed.ocr_pages == 1
    assert len(parsed.pages) == 3
    assert parsed.pages[0].startswith("FIRST")  # page 1 untouched
    assert "OCR TEXT FOR PAGE 2" in parsed.pages[1]  # OCR text at index 1 = page 2
    assert parsed.pages[2].startswith("THIRD")  # page 3 untouched


def test_scanned_pdf_without_tesseract_gives_a_clear_error(monkeypatch):
    monkeypatch.setattr(extract, "ocr_available", lambda: False)
    with pytest.raises(ExtractionError) as err:
        read_pdf(SCANNED.read_bytes())
    message = str(err.value)
    assert "looks scanned" in message and "OCR isn't installed" in message
    assert "Tesseract" in message  # says how to fix it


def test_scanned_upload_without_tesseract_is_a_422(client, monkeypatch):
    monkeypatch.setattr(extract, "ocr_available", lambda: False)
    r = client.post("/api/protocols", files={"file": ("scan.pdf", SCANNED.read_bytes(), "application/pdf")})
    assert r.status_code == 422
    assert "OCR isn't installed" in r.json()["detail"]


def test_too_many_scanned_pages_is_refused(stub_ocr):
    doc = pymupdf.open()
    for _ in range(3):
        _image_page(doc)
    data = doc.tobytes()
    with pytest.raises(ProtocolTooLongError, match="3 scanned pages"):
        parse_pdf(data, "scan.pdf", max_ocr_pages=2)
    assert stub_ocr == []  # refused before any OCR work


def test_ocr_stops_at_the_deadline(stub_ocr):
    import time

    with pytest.raises(ExtractionError, match="took too long"):
        parse_pdf(SCANNED.read_bytes(), "scan.pdf", deadline=time.monotonic() - 1)


def test_unreadable_scan_reports_no_text_even_after_ocr(monkeypatch):
    monkeypatch.setattr(extract, "ocr_available", lambda: True)
    monkeypatch.setattr(extract, "_ocr_page", lambda page: "")
    with pytest.raises(ExtractionError, match="even after trying OCR"):
        read_pdf(SCANNED.read_bytes())


def test_blank_pages_are_not_sent_to_ocr(stub_ocr):
    doc = pymupdf.open()
    doc.new_page().insert_textbox(pymupdf.Rect(50, 50, 550, 750), TEXT_PAGE * 2, fontsize=10)
    doc.new_page()  # blank: no text, no image
    parse_pdf(doc.tobytes(), "blank.pdf")
    assert stub_ocr == []


def test_scanned_upload_reports_ocr_pages(client, stub_ocr):
    r = client.post("/api/protocols", files={"file": ("scan.pdf", SCANNED.read_bytes(), "application/pdf")})
    assert r.status_code == 200, r.text
    assert r.json()["extraction_info"]["ocr_pages"] == 1


# ---------- real Tesseract ----------

@needs_tesseract
def test_real_ocr_reads_the_scanned_fixture():
    parsed = parse_pdf(SCANNED.read_bytes(), "scanned_protocol.pdf")
    assert parsed.ocr_pages == 1
    text = parsed.pages[0]
    assert "Synthetic Test Study of Drug X" in text
    # Tesseract may read the zeros as letter O ("NCTOO000000"); the registry
    # id finder corrects that (see test_registry_id_tolerates_ocr_letter_o).
    assert "NCT" in text


@needs_tesseract
def test_scanned_upload_produces_a_plan(client):
    r = client.post(
        "/api/protocols", files={"file": ("scanned_protocol.pdf", SCANNED.read_bytes(), "application/pdf")}
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["protocol"]["registry_id"] == "NCT00000000"
    assert body["safety"], "the 24-hour SAE rule should be found in the OCR text"
    assert body["extraction_info"]["ocr_pages"] == 1


@needs_tesseract
def test_real_ocr_writes_no_files(tmp_path, monkeypatch):
    # Privacy rule: protocol content is never written to disk, OCR included.
    import tempfile

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    parse_pdf(SCANNED.read_bytes(), "scanned_protocol.pdf")
    assert list(tmp_path.iterdir()) == []


def test_registry_id_tolerates_ocr_letter_o():
    # The exact misread Tesseract produced on CI for the scanned fixture.
    assert extract.find_registry_id(["Registry ID: NCTOO000000\nPhase:2"], "scan.pdf") == "NCT00000000"
    assert extract.find_registry_id(["NCT03872401"], None) == "NCT03872401"
    # Nine characters is not an NCT id, with or without an O.
    assert extract.find_registry_id(["NCT0387240O1"], None) is None
