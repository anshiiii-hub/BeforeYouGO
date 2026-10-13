"""Sync resilience (one adapter failing), URL normalisation."""

from __future__ import annotations

from sqlalchemy import select

from app.models import Event, Source, SyncRun
from app.services.sources.registry import seed_sources
from app.services.sync import run_source_sync, sync_all_sources
from app.services.urls import canonicalize_url, display_url, is_safe_link
from tests.support.adapters import FixtureAdapter, install
from tests.support.factories import auth, days, make_user


def rec(i, title, **kw):
    return {"id": i, "title": title, "start": days(30).isoformat(), "city": "Pune", "format": "offline", **kw}


def test_one_failing_adapter_does_not_break_others(db):
    good = FixtureAdapter("good", [rec("1", "Good Event One")])
    bad = FixtureAdapter("bad", crash=True)
    install(bad, good)
    out = {r["source"]: r for r in sync_all_sources("manual")}
    assert out["good"]["status"] == "success" and out["good"]["created"] == 1
    assert out["bad"]["status"] == "failed"
    db.expire_all()
    assert db.scalars(select(Event)).one().title == "Good Event One"
    bad_src = db.scalar(select(Source).where(Source.key == "bad"))
    assert bad_src.status == "degraded" and bad_src.consecutive_failures == 1
    good_src = db.scalar(select(Source).where(Source.key == "good"))
    assert good_src.status == "active" and good_src.last_success_at is not None


def test_api_keeps_working_with_failed_source(db, client):
    install(FixtureAdapter("good", [rec("1", "Good Event One")]), FixtureAdapter("bad", crash=True))
    sync_all_sources("manual")
    r = client.get("/api/events")
    assert r.status_code == 200 and r.json()["total"] == 1
    idx = r.json()["index"]
    assert idx["state"] == "degraded" and idx["connectors_failing"][0]["key"] == "bad"


def test_partial_failure_marks_run_partial_and_keeps_good_records(db):
    ad = FixtureAdapter("half", [rec("1", "Half Event One")], errors=[{"document": "doc2", "code": "http_500", "message": "boom"}])
    install(ad)
    with __import__("app.core.db", fromlist=["x"]).session_scope() as s:
        seed_sources(s)
    res = run_source_sync("half")
    assert res["status"] == "partial" and res["created"] == 1 and res["errors"][0]["code"] == "http_500"
    db.expire_all()
    assert db.scalar(select(Source).where(Source.key == "half")).status == "degraded"


def test_record_that_fails_to_normalize_is_skipped_not_fatal(db):
    ad = FixtureAdapter("mixed", [rec("1", "Fine Event One"), {"id": "2"}])  # second record has no title -> KeyError
    install(ad)
    with __import__("app.core.db", fromlist=["x"]).session_scope() as s:
        seed_sources(s)
    res = run_source_sync("mixed")
    assert res["created"] == 1 and res["skipped"] == 1
    db.expire_all()
    run = db.scalars(select(SyncRun)).one()
    assert run.skipped_count == 1 and run.errors[0]["code"] == "record_failed"


def test_sync_missing_record_flags_removed_event(db):
    ad = FixtureAdapter("src", [rec("1", "Vanishing Event"), rec("2", "Staying Event")])
    install(ad)
    with __import__("app.core.db", fromlist=["x"]).session_scope() as s:
        seed_sources(s)
    run_source_sync("src")
    ad.records = [ad.records[1]]
    res = run_source_sync("src")
    assert res["missing"] == 1
    db.expire_all()
    by = {e.title: e for e in db.scalars(select(Event))}
    assert by["Vanishing Event"].lifecycle_status == "removed_from_source"
    assert by["Staying Event"].lifecycle_status == "scheduled"


def test_admin_trigger_sync_runs_and_requires_admin(db, client):
    ad = FixtureAdapter("src", [rec("1", "Triggered Event")])
    install(ad)
    student, admin = make_user(db, "student"), make_user(db, "admin")
    assert client.post("/api/admin/sources/src/sync", headers=auth(student)).status_code == 403
    assert client.post("/api/admin/sources/src/sync").status_code == 401
    assert client.post("/api/admin/sources/src/sync", headers=auth(admin)).status_code == 202
    db.expire_all()
    assert db.scalars(select(Event)).one().title == "Triggered Event"
    assert client.post("/api/admin/sources/nope/sync", headers=auth(admin)).json()["error"]["code"] == "no_connector"


# ----------------------------------------------------------- URL normalisation


def test_canonicalize_url_rules():
    c = canonicalize_url
    assert c("HTTP://WWW.Example.COM:80/a//b/?utm_source=x&b=2&a=1&fbclid=z#frag") == "https://example.com/a/b?a=1&b=2"
    assert c("example.com/path/") == "https://example.com/path"
    assert c("https://example.com") == c("https://example.com/") == c("http://www.example.com/")
    assert c("https://example.com:8443/x") == "https://example.com:8443/x"
    assert c("https://example.com/x?ref=tw&id=7") == "https://example.com/x?id=7"


def test_canonicalize_rejects_unusable_urls():
    for bad in (None, "", "   ", "ftp://example.com/x", "javascript:alert(1)", "https://"):
        assert canonicalize_url(bad) is None


def test_display_url_and_safe_link():
    assert display_url("Example.com/Path?utm_x=1&k=v#f") == "https://example.com/Path?k=v"
    assert display_url("javascript:alert(1)") is None
    assert is_safe_link("https://a.test.example") and is_safe_link("http://a.test.example")
    assert not is_safe_link("javascript:alert(1)") and not is_safe_link("data:text/html,x") and not is_safe_link(None)
