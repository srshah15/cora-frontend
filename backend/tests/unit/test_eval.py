"""Tests for the accuracy evaluation script (issue #35). Offline: the Claude
column uses the FakeLLM from conftest.py."""

import json

import pytest
from pydantic import ValidationError

import eval as ev

# The truth for tests/fixtures/sample_protocol.pdf. We wrote that synthetic
# page (make_fixtures.py), so this answer file is known to be correct.
SAMPLE_EXPECTED = {
    "status": "VERIFIED",
    "verified_by": "test suite (synthetic fixture)",
    "verified_on": "2026-11-11",
    "nct_id": "NCT00000000",
    "source_url": None,
    "visits": [
        {"id": "V1", "name": "Screening"},
        {"id": "V2", "name": "Baseline"},
        {"id": "V3", "name": "Follow-up"},
    ],
    "procedures": [
        {"name": "Informed consent", "visits": ["V1"]},
        {"name": "Physical exam", "visits": ["V1", "V2"]},
        {"name": "Blood draw", "visits": ["V1", "V3"]},
        {"name": "ECG", "visits": ["V2"]},
        {"name": "Dosing", "visits": ["V2"]},
        {"name": "Adverse event review", "visits": ["V3"]},
    ],
    "staffing": [{"role": "Principal Investigator"}, {"role": "Study Coordinator"}, {"role": "Research Pharmacist"}],
    "safety": [{"event": "Serious adverse event"}],
    "billing": [],
    "equipment": [],
    "pharmacy": [],
    "technology": [],
}


@pytest.fixture
def protocols_dir(tmp_path, sample_pdf_bytes):
    """A one-protocol test set in a temp dir. Returns a function to write its answer file."""
    sub = tmp_path / "NCT00000000"
    sub.mkdir()
    (sub / "protocol.pdf").write_bytes(sample_pdf_bytes)

    def _write(**overrides):
        (sub / "expected.json").write_text(json.dumps({**SAMPLE_EXPECTED, **overrides}))
        return tmp_path

    return _write


# ---------- normalize / match ----------

def test_normalize_strips_punctuation_case_plurals_and_applies_synonyms():
    assert ev.normalize("12-Lead ECGs") == "ecg"
    assert ev.normalize("Electrocardiogram (EKG)") == "ecg ecg"
    assert ev.normalize("Informed Consent Form") == "informed consent"
    assert ev.normalize("Physical examinations") == "physical exam"
    assert ev.normalize("Glass") == "glass"  # "ss" is not a plural
    assert ev.normalize(None) == ""


def test_match_is_one_to_one_and_best_first():
    # Both extracted items resemble "physical exam"; only the better one may claim it.
    pairs = ev.match(["Physical exam", "Vital signs"], ["Physical exam", "Physical exam repeat", "Vitals"])
    assert pairs == {0: 0, 1: 2}


def test_match_respects_threshold():
    assert ev.match(["Blood draw"], ["Urine sample"]) == {}
    # 2 shared words of 4 distinct = 0.5, exactly the threshold.
    assert ev.match(["adverse event review"], ["adverse event assessment"]) == {0: 0}


def test_empty_sides_are_na_not_perfect():
    s = ev.Score(expected=0, extracted=0, matched=0)
    assert s.precision is None and s.recall is None
    assert ev._pr(s) == "n/a / n/a"


# ---------- answer file ----------

def test_answer_file_requires_every_category():
    bad = {k: v for k, v in SAMPLE_EXPECTED.items() if k != "technology"}
    with pytest.raises(ValidationError):
        ev.Expected.model_validate(bad)


def test_draft_status_or_missing_signoff_is_unverified():
    assert ev.Expected.model_validate(SAMPLE_EXPECTED).verified
    assert not ev.Expected.model_validate({**SAMPLE_EXPECTED, "status": "DRAFT – NEEDS HUMAN VERIFICATION"}).verified
    assert not ev.Expected.model_validate({**SAMPLE_EXPECTED, "verified_on": None}).verified


# ---------- scoring a plan ----------

def test_procedure_visit_pairs_use_aligned_visit_ids():
    expected = ev.Expected.model_validate(SAMPLE_EXPECTED)
    # The extractor named its visits differently (A/B/C) and swapped one tag.
    plan = {
        "visits": [{"id": "A", "name": "Screening"}, {"id": "B", "name": "Baseline"}, {"id": "C", "name": "Follow up"}],
        "procedures": [
            {"name": "Informed consent", "visits": ["A"]},  # right
            {"name": "Physical exam", "visits": ["A", "C"]},  # A right, C wrong (should be B)
        ],
    }
    s = ev.score_plan(expected, plan)["procedure→visit"]
    assert (s.expected, s.extracted, s.matched) == (8, 3, 2)


def test_keyword_run_scores_sample(protocols_dir):
    protocol = ev.load_protocols(protocols_dir())[0]
    run = ev.run_extractor(protocol, "keyword")
    assert run.error is None and not run.fallback
    procs = run.scores["procedures"]
    # Keyword finds informed consent, physical examination, adverse event
    # assessment and 12-lead ECG: all real, 4 of the 6 expected.
    assert (procs.matched, procs.extracted, procs.expected) == (4, 4, 6)
    assert run.scores["safety"].recall == 1.0
    assert run.scores["visits"].recall == 0.0  # keyword mode finds no visits


# ---------- command line ----------

def test_empty_dir_prints_hint(tmp_path, capsys):
    assert ev.main(["--protocols-dir", str(tmp_path / "missing")]) == 0
    assert "No protocols in" in capsys.readouterr().out


def test_draft_is_refused_without_flag(protocols_dir, capsys):
    d = protocols_dir(status="DRAFT – NEEDS HUMAN VERIFICATION", verified_by=None, verified_on=None)
    assert ev.main(["--protocols-dir", str(d)]) == 1
    out = capsys.readouterr().out
    assert "unverified drafts" in out and "%" not in out


def test_draft_with_flag_labels_every_row(protocols_dir, capsys):
    d = protocols_dir(status="DRAFT – NEEDS HUMAN VERIFICATION", verified_by=None, verified_on=None)
    assert ev.main(["--protocols-dir", str(d), "--allow-draft"]) == 0
    out = capsys.readouterr().out
    rows = [line for line in out.splitlines() if line.startswith(ev.CATEGORIES + ("procedure→visit",))]
    assert rows and all(ev.DRAFT_LABEL in line for line in rows)


def test_verified_run_prints_table_with_llm_not_run(protocols_dir, capsys):
    assert ev.main(["--protocols-dir", str(protocols_dir())]) == 0
    out = capsys.readouterr().out
    assert "procedures" in out and "100% / 67%" in out  # keyword procedures
    assert "not run" in out and ev.DRAFT_LABEL not in out


def test_live_runs_claude_column_with_fake_client(protocols_dir, llm_mode, llm_payload, monkeypatch, capsys):
    llm_mode.queue(llm_payload)
    monkeypatch.setattr("builtins.input", lambda prompt: "y")
    assert ev.main(["--protocols-dir", str(protocols_dir()), "--live"]) == 0
    out = capsys.readouterr().out
    assert len(llm_mode.calls) == 1
    visits = next(line for line in out.splitlines() if line.startswith("visits"))
    assert visits.split()[-3:] == ["100%", "/", "100%"]  # LLM found all three visits
    pairs = next(line for line in out.splitlines() if line.startswith("procedure→visit"))
    assert "100% / 62%" in pairs  # 5 correct pairs of 8 expected


def test_live_cancel_sends_nothing(protocols_dir, llm_mode, monkeypatch, capsys):
    monkeypatch.setattr("builtins.input", lambda prompt: "n")
    assert ev.main(["--protocols-dir", str(protocols_dir()), "--live"]) == 1
    assert llm_mode.calls == []
    assert "Estimated cost" not in capsys.readouterr().out  # the prompt went to input(), not print


def test_live_without_key_stops(protocols_dir, monkeypatch, capsys):
    # The autouse no_api_keys fixture has already removed the key.
    assert ev.main(["--protocols-dir", str(protocols_dir()), "--live"]) == 2
    assert "ANTHROPIC_API_KEY" in capsys.readouterr().out
