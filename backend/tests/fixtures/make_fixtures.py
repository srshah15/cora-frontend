"""Generates small, synthetic PDF fixtures for tests.

Contains no real or confidential protocol data. Re-run to regenerate:
    python tests/fixtures/make_fixtures.py
"""
from pathlib import Path

import pymupdf

FIXTURE_DIR = Path(__file__).parent

SAMPLE_TEXT = """SAMPLE PROTOCOL - TEST FIXTURE
Study Title: Synthetic Test Study of Drug X
Registry ID: NCT00000000
Phase: 2

SCHEDULE OF ACTIVITIES
Visit 1 - Screening (Day -28 to Day -1): informed consent, physical exam, blood draw
Visit 2 - Baseline (Day 1): physical exam, ECG, dosing
Visit 3 - Follow-up (Week 4 +/- 3 days): blood draw, adverse event review

SAFETY REPORTING
Serious adverse events must be reported to the sponsor within 24 hours.

STAFFING
Principal Investigator; Study Coordinator; Research Pharmacist
"""


def make_sample_protocol(path: Path) -> None:
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((50, 72), SAMPLE_TEXT, fontsize=10)
    doc.save(path)
    doc.close()


if __name__ == "__main__":
    out = FIXTURE_DIR / "sample_protocol.pdf"
    make_sample_protocol(out)
    print(f"Wrote {out}")