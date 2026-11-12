"""Persistence tests (issues #25, #26, #27) on in-memory SQLite.

Supabase is never contacted: DATABASE_URL is removed for every test and the
`db_on` fixture points it at SQLite; the network guard would fail anything else.
"""

import logging
from pathlib import Path

import pymupdf
import pytest
from sqlalchemy import inspect, select, text

import main
from conftest import REVIEWER_A, REVIEWER_B
from db_models import Base, Plan, Protocol, Review
from models import OperationalPlan

FIXTURE_STRINGS = ("Synthetic Test Study", "SCHEDULE OF ACTIVITIES", "Research Pharmacist", "within 24 hours")


def _upload(client, data, name="sample_protocol.pdf", headers=None):
    return client.post("/api/protocols", files={"file": (name, data, "application/pdf")}, headers=headers or {})


def _variant(text_line: str) -> bytes:
    """A different file for the same study (same NCT id, different bytes)."""
    doc = pymupdf.open()
    doc.new_page().insert_text(
        (50, 72),
        "PROTOCOL AMENDMENT\nStudy Title: Synthetic Test Study of Drug X\nRegistry ID: NCT00000000\n"
        + text_line + "\nSerious adverse events must be reported to the sponsor within 24 hours.\n" * 3,
        fontsize=10,
    )
    return doc.tobytes()


def _decision(status="accepted", **extra):
    return {"status": status, "reviewer": "Reviewer A", "at": "2026-11-11T10:00:00Z", **extra}


# ---------- persistence off ----------

def test_without_database_url_upload_works_and_nothing_persists(client, sample_pdf_bytes):
    r = _upload(client, sample_pdf_bytes)
    assert r.status_code == 200
    body = r.json()
    assert body["plan_id"] is None and body["reused"] is False and body["reviews"] == {}


def test_plan_endpoints_say_saving_is_not_configured(client, as_reviewer):
    r = client.get("/api/plans", headers=as_reviewer())
    assert r.status_code == 503
    assert "DATABASE_URL" in r.json()["detail"]


# ---------- #25 privacy ----------

def test_only_id_fields_plan_and_reviews_are_stored(client, db_on, sample_pdf_bytes, as_reviewer):
    plan_id = _upload(client, sample_pdf_bytes).json()["plan_id"]
    client.put(f"/api/plans/{plan_id}/reviews/safety:0", json=_decision(), headers=as_reviewer())

    with db_on.session_scope() as s:
        protocol = s.scalars(select(Protocol)).one()
        assert len(protocol.content_hash) == 64
        assert protocol.nct_id == "NCT00000000"
        assert protocol.version == 1
        plan = s.scalars(select(Plan)).one()
        OperationalPlan.model_validate(plan.plan_json)  # the stored plan is a valid plan
        assert s.scalars(select(Review)).one().item_key == "safety:0"


def test_no_pdf_bytes_or_raw_text_in_any_table_or_log(client, db_on, sample_pdf_bytes, caplog, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    with caplog.at_level(logging.DEBUG):
        assert _upload(client, sample_pdf_bytes).status_code == 200

    # Every value of every column of every table, as one string.
    dump = []
    with db_on.get_engine().connect() as conn:
        for table in Base.metadata.sorted_tables:
            for row in conn.execute(text(f"SELECT * FROM {table.name}")):
                dump.extend(str(v) for v in row)
    stored = "\n".join(dump)

    assert "%PDF" not in stored and "%PDF" not in caplog.text
    raw_page = pymupdf.open(stream=sample_pdf_bytes, filetype="pdf")[0].get_text()
    assert raw_page.strip() not in stored
    # Sentences from the protocol body that are not extracted fields.
    for phrase in ("SCHEDULE OF ACTIVITIES", "Research Pharmacist", "must be reported to the sponsor"):
        assert phrase not in stored
    for phrase in FIXTURE_STRINGS:
        assert phrase not in caplog.text
    assert list(tmp_path.iterdir()) == []  # nothing written to disk


def test_no_table_has_a_column_for_file_content():
    columns = {c.name for t in Base.metadata.sorted_tables for c in t.columns}
    assert not columns & {"pdf", "pdf_bytes", "file", "content", "raw_text", "text", "pages"}


def test_migration_creates_the_same_tables_as_the_models(tmp_path):
    """The Alembic migration and db_models.py must not drift apart."""
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import create_engine

    url = f"sqlite+pysqlite:///{tmp_path / 'migrated.db'}"
    cfg = Config(str(Path(main.__file__).parent / "alembic.ini"))
    cfg.set_main_option("script_location", str(Path(main.__file__).parent / "migrations"))
    cfg.set_main_option("sqlalchemy.url", url)
    command.upgrade(cfg, "head")

    insp = inspect(create_engine(url))
    for table in Base.metadata.sorted_tables:
        migrated = {c["name"] for c in insp.get_columns(table.name)}
        assert migrated == {c.name for c in table.columns}, table.name
    uniques = {tuple(u["column_names"]) for u in insp.get_unique_constraints("reviews")}
    assert ("plan_id", "reviewer_id", "item_key") in uniques
    assert any(u["column_names"] == ["content_hash"] for u in insp.get_unique_constraints("protocols"))


# ---------- #27 reuse ----------

def test_second_upload_of_same_pdf_makes_no_llm_call(client, db_on, llm_mode, llm_payload, sample_pdf_bytes):
    llm_mode.queue(llm_payload)  # only one answer is queued; a second call would fail the test
    first = _upload(client, sample_pdf_bytes).json()
    second = _upload(client, sample_pdf_bytes).json()

    assert len(llm_mode.calls) == 1
    assert first["reused"] is False and second["reused"] is True
    assert second["plan_id"] == first["plan_id"]
    assert second["visits"] == first["visits"] and second["extraction"] == "llm"


def test_reuse_returns_only_the_uploaders_own_reviews(client, db_on, sample_pdf_bytes, as_reviewer):
    plan_id = _upload(client, sample_pdf_bytes).json()["plan_id"]
    client.put(f"/api/plans/{plan_id}/reviews/safety:0", json=_decision(comment="A's note"), headers=as_reviewer())

    again_a = _upload(client, sample_pdf_bytes, headers=as_reviewer()).json()
    again_b = _upload(client, sample_pdf_bytes, headers=as_reviewer(REVIEWER_B, "Reviewer B")).json()
    anonymous = _upload(client, sample_pdf_bytes).json()

    assert again_a["reviews"]["safety:0"]["comment"] == "A's note"
    assert again_b["reviews"] == {} and anonymous["reviews"] == {}


def test_different_file_of_same_study_is_extracted_fresh_as_new_version(client, db_on, llm_mode, llm_payload, sample_pdf_bytes):
    llm_mode.queue(llm_payload, llm_payload)
    v1 = _upload(client, sample_pdf_bytes).json()
    v2 = _upload(client, _variant("Amendment 2: visit window widened."), "amendment.pdf").json()

    assert len(llm_mode.calls) == 2  # the new file was not served from the old plan
    assert v2["reused"] is False
    assert (v1["version"], v2["version"]) == (1, 2)
    assert v1["plan_id"] != v2["plan_id"]


def test_same_protocol_number_without_nct_is_also_a_new_version(client, db_on, make_pdf):
    body = "Protocol Number: ABC-123\n" + "Vital signs and adverse events are recorded at each visit.\n" * 6
    v1 = _upload(client, make_pdf([body])).json()
    v2 = _upload(client, make_pdf([body + "Amended.\n"])).json()
    unrelated = _upload(client, make_pdf(["Protocol Number: XYZ-9\n" + "Vital signs are recorded.\n" * 8])).json()
    assert (v1["version"], v2["version"], unrelated["version"]) == (1, 2, 1)
    assert v1["protocol"]["protocol_number"] == "ABC-123"


def test_fallback_plans_are_not_stored(client, db_on, llm_mode, llm_payload, sample_pdf_bytes, api_error):
    llm_mode.queue(api_error(401))
    first = _upload(client, sample_pdf_bytes).json()
    assert first["extraction_info"]["fallback"] is True and first["plan_id"] is None

    # Once the LLM works again, the same file gets a real LLM plan.
    llm_mode.queue(llm_payload)
    second = _upload(client, sample_pdf_bytes).json()
    assert second["extraction"] == "llm" and second["plan_id"] and second["reused"] is False


def test_keyword_plan_is_upgraded_when_llm_is_switched_on(client, db_on, fake_llm, llm_payload, sample_pdf_bytes, monkeypatch):
    stored = _upload(client, sample_pdf_bytes).json()  # keyword mode
    assert stored["extraction"] == "keyword"

    monkeypatch.setenv("CORA_EXTRACTOR", "claude")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-not-real")
    fake_llm.queue(llm_payload)
    upgraded = _upload(client, sample_pdf_bytes).json()
    assert upgraded["extraction"] == "llm"
    assert upgraded["plan_id"] == stored["plan_id"]  # same protocol row, better plan
    assert _upload(client, sample_pdf_bytes).json()["reused"] is True
    assert len(fake_llm.calls) == 1


def test_race_on_same_file_resolves_to_one_row(db_on, sample_pdf_bytes):
    import repository as repo
    from extractor import KeywordExtractor
    from extract import parse_pdf

    plan = KeywordExtractor().extract(parse_pdf(sample_pdf_bytes, "a.pdf"))
    with db_on.session_scope() as s:
        first = repo.save_plan(s, "a" * 64, plan)
    with db_on.session_scope() as s:  # a second request that missed the lookup
        second = repo.save_plan(s, "a" * 64, plan)
    assert second.plan_id == first.plan_id
    with db_on.session_scope() as s:
        assert len(list(s.scalars(select(Protocol)))) == 1


# ---------- #26 endpoints ----------

@pytest.fixture
def plan_id(client, db_on, sample_pdf_bytes):
    return _upload(client, sample_pdf_bytes).json()["plan_id"]


def test_list_and_get_plan(client, plan_id, as_reviewer):
    listing = client.get("/api/plans", headers=as_reviewer()).json()["plans"]
    assert [p["id"] for p in listing] == [plan_id]
    assert listing[0]["nct_id"] == "NCT00000000" and listing[0]["version"] == 1

    detail = client.get(f"/api/plans/{plan_id}", headers=as_reviewer()).json()
    OperationalPlan.model_validate(detail["plan"])
    assert detail["reviews"] == {} and detail["other_reviewer_count"] == 0


def test_reviewers_never_see_or_overwrite_each_others_decisions(client, plan_id, as_reviewer):
    a, b = as_reviewer(), as_reviewer(REVIEWER_B, "Reviewer B")
    url = f"/api/plans/{plan_id}/reviews/safety:0"
    assert client.put(url, json=_decision("accepted", comment="A says yes"), headers=a).status_code == 200
    assert client.put(url, json=_decision("rejected", comment="B says no", reviewer="Reviewer B"), headers=b).status_code == 200

    seen_a = client.get(f"/api/plans/{plan_id}", headers=a).json()
    seen_b = client.get(f"/api/plans/{plan_id}", headers=b).json()
    assert seen_a["reviews"]["safety:0"]["status"] == "accepted"
    assert seen_a["reviews"]["safety:0"]["comment"] == "A says yes"
    assert seen_b["reviews"]["safety:0"]["status"] == "rejected"
    assert "B says no" not in str(seen_a) and "A says yes" not in str(seen_b)
    # Each sees only a count of the others.
    assert seen_a["other_reviewer_count"] == 1 and seen_b["other_reviewer_count"] == 1

    listing = client.get("/api/plans", headers=a).json()["plans"][0]
    assert listing["my_review_count"] == 1 and listing["other_reviewer_count"] == 1


def test_put_again_updates_your_own_decision(client, plan_id, as_reviewer):
    url = f"/api/plans/{plan_id}/reviews/safety:0"
    client.put(url, json=_decision("accepted"), headers=as_reviewer())
    edit = _decision("edited", values={"timeline": "Within 48 hours"}, original={"timeline": "Within 24 hours"})
    saved = client.put(url, json=edit, headers=as_reviewer()).json()
    assert saved["status"] == "edited" and saved["values"] == {"timeline": "Within 48 hours"}

    detail = client.get(f"/api/plans/{plan_id}", headers=as_reviewer()).json()
    assert len(detail["reviews"]) == 1
    # One reviewer's edit never changes the shared plan.
    assert detail["plan"]["safety"][0]["timeline"] != "Within 48 hours"


def test_delete_plan_removes_only_the_callers_decisions(client, plan_id, as_reviewer):
    a, b = as_reviewer(), as_reviewer(REVIEWER_B, "Reviewer B")
    for key in ("safety:0", "procedures:0"):
        client.put(f"/api/plans/{plan_id}/reviews/{key}", json=_decision(), headers=a)
    client.put(f"/api/plans/{plan_id}/reviews/safety:0", json=_decision("rejected"), headers=b)

    r = client.delete(f"/api/plans/{plan_id}", headers=a)
    assert r.status_code == 200 and r.json() == {"deleted": 2}
    assert client.get(f"/api/plans/{plan_id}", headers=a).json()["reviews"] == {}
    assert client.get(f"/api/plans/{plan_id}", headers=b).json()["reviews"]["safety:0"]["status"] == "rejected"
    assert client.get(f"/api/plans/{plan_id}", headers=a).status_code == 200  # the plan itself remains


def test_undo_one_decision(client, plan_id, as_reviewer):
    a = as_reviewer()
    for key in ("safety:0", "procedures:0"):
        client.put(f"/api/plans/{plan_id}/reviews/{key}", json=_decision(), headers=a)
    assert client.delete(f"/api/plans/{plan_id}/reviews/safety:0", headers=a).json() == {"deleted": 1}
    assert list(client.get(f"/api/plans/{plan_id}", headers=a).json()["reviews"]) == ["procedures:0"]


def test_reviews_of_two_plans_never_mix(client, db_on, sample_pdf_bytes, as_reviewer):
    plan_a = _upload(client, sample_pdf_bytes).json()["plan_id"]
    plan_b = _upload(client, _variant("Another file."), "b.pdf").json()["plan_id"]
    assert plan_a != plan_b
    client.put(f"/api/plans/{plan_a}/reviews/safety:0", json=_decision(comment="on plan A"), headers=as_reviewer())

    assert client.get(f"/api/plans/{plan_b}", headers=as_reviewer()).json()["reviews"] == {}
    assert client.delete(f"/api/plans/{plan_b}", headers=as_reviewer()).json() == {"deleted": 0}
    assert "on plan A" in str(client.get(f"/api/plans/{plan_a}", headers=as_reviewer()).json())


@pytest.mark.parametrize(
    "key, body, status",
    [
        ("safety:0", {"status": "maybe"}, 422),          # not a valid status
        ("safety:0", {"comment": "no status"}, 422),     # required field missing
        ("safety:99", {"status": "accepted"}, 422),      # no such item
        ("visits:0", {"status": "accepted"}, 422),       # section isn't reviewable
        ("nonsense", {"status": "accepted"}, 422),       # not "<section>:<index>"
    ],
)
def test_review_bodies_and_keys_are_validated(client, plan_id, as_reviewer, key, body, status):
    r = client.put(f"/api/plans/{plan_id}/reviews/{key}", json=body, headers=as_reviewer())
    assert r.status_code == status, r.text


def test_reviewer_header_is_required_and_must_be_a_uuid(client, plan_id):
    assert client.get("/api/plans").status_code == 400
    r = client.get(f"/api/plans/{plan_id}", headers={"X-Reviewer-Id": "not-a-uuid"})
    assert r.status_code == 400 and "UUID" in r.json()["detail"]


def test_unknown_plan_is_404(client, db_on, as_reviewer):
    missing = "00000000-0000-4000-8000-000000000000"
    assert client.get(f"/api/plans/{missing}", headers=as_reviewer()).status_code == 404
    assert client.put(f"/api/plans/{missing}/reviews/safety:0", json=_decision(), headers=as_reviewer()).status_code == 404


def test_reviewer_name_header_is_url_decoded(client, plan_id, as_reviewer):
    headers = as_reviewer(name="Jos%C3%A9%20N%C3%BA%C3%B1ez")
    body = {"status": "accepted"}
    saved = client.put(f"/api/plans/{plan_id}/reviews/safety:0", json=body, headers=headers).json()
    assert saved["reviewer"] == "José Núñez"
