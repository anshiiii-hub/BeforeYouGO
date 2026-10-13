"""Data discovery: normalisation, dedupe, unknown-stays-unknown, refresh/provenance, lifecycle."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.models import DuplicateCandidate, Event, EventFieldAssertion, EventVersion, SourceRecord
from app.services.event_fields import FIELD_SPECS
from app.services.ingest import mark_missing_records, norm_title
from app.services.sources.base import RawRecord
from app.services.sources.github_conferences import DevelopersEventsAdapter, TechConferencesAdapter
from app.services.sources.ics_feed import IcsFeedAdapter
from tests.support.adapters import FixtureAdapter, ingest, install, source_row
from tests.support.factories import days

START = days(40).isoformat()
END = days(41).isoformat()


def rec(i="a1", **kw):
    base = {"id": i, "title": "Test Summit Alpha", "url": "https://alpha.test.example/summit", "start": START, "end": END, "city": "Pune",
            "country": "India", "format": "offline"}
    base.update(kw)
    return base


# ----------------------------------------------------------- multiple adapters -> one schema


def test_different_adapters_normalize_to_same_schema():
    tc = TechConferencesAdapter()
    n1 = tc.normalize(RawRecord("t1", {"name": "TEST Conf", "url": "https://tc.test.example/", "startDate": "2030-05-01", "endDate": "2030-05-02",
                                       "city": "Bangalore", "country": "India", "online": False, "_topic": "ai"}))
    de = DevelopersEventsAdapter()
    ms = int(datetime(2030, 5, 1, tzinfo=UTC).timestamp() * 1000)
    n2 = de.normalize(RawRecord("d1", {"name": "TEST Dev Days", "hyperlink": "https://de.test.example/", "date": [ms, ms], "city": "Pune",
                                       "country": "India", "location": "Pune, India"}))
    ics = IcsFeedAdapter(urls=[])
    n3 = ics.normalize(RawRecord("i1", {"summary": "TEST Meetup", "start": "2030-05-01", "start_is_datetime": False, "end": "2030-05-02",
                                        "end_is_datetime": False, "location": "Delhi", "url": "https://ics.test.example/m", "categories": []}))
    fx = FixtureAdapter("fx").normalize(RawRecord("f1", rec()))
    for n in (n1, n2, n3, fx):
        assert set(n.values) <= set(FIELD_SPECS)
        assert n.values["title"]
        assert n.values["start_date"] is not None
    assert n1.values["city"] == "Bengaluru"  # canonical city name
    assert n1.values["format"] == "offline"


def test_missing_values_stay_unknown_through_ingest(db):
    (ev,) = ingest(db, FixtureAdapter("fx", [{"id": "x", "title": "Bare Event Beta"}]))
    assert ev.fee_status == "unknown" and ev.fee_amount is None  # never free
    assert ev.registration_deadline is None
    assert ev.start_date is None and ev.format == "unknown"
    assert ev.offers_certificate is None and ev.allows_cross_college_teams is None


def test_missing_price_is_not_free_but_explicit_free_is(db):
    evs = ingest(db, FixtureAdapter("fx", [rec("1", title="Paid One", url=None, fee=500), rec("2", title="Free One", url=None, fee="free", start=days(50).isoformat()),
                                            rec("3", title="Unknown One", url=None, start=days(60).isoformat())]))
    by = {e.title: e for e in evs}
    assert by["Paid One"].fee_status == "paid" and float(by["Paid One"].fee_amount) == 500
    assert by["Free One"].fee_status == "free"
    assert by["Unknown One"].fee_status == "unknown"


def test_absent_deadline_null_and_present_deadline_kept(db):
    dl = (datetime.now(UTC) + timedelta(days=10)).replace(microsecond=0)
    evs = ingest(db, FixtureAdapter("fx", [rec("1", title="No Deadline X", url=None), rec("2", title="With Deadline Y", url=None, start=days(70).isoformat(),
                                                                                       deadline=dl.isoformat())]))
    by = {e.title: e for e in evs}
    assert by["No Deadline X"].registration_deadline is None
    assert by["With Deadline Y"].registration_deadline == dl


def test_missing_accessibility_is_not_unavailable(db, client):
    evs = ingest(db, FixtureAdapter("fx", [rec("1", title="Silent Event", url=None), rec("2", title="Documented Event", url=None, start=days(80).isoformat(),
                                                                                       accessibility="Wheelchair accessible venue")]))
    by = {e.title: e for e in evs}
    r = client.get(f"/api/events/{by['Silent Event'].id}").json()
    states = {i["key"]: i["state"] for i in r["accessibility"]["items"]}
    assert states and set(states.values()) == {"not_documented"}
    assert "confirmed_unavailable" not in states.values()
    r2 = client.get(f"/api/events/{by['Documented Event'].id}").json()
    assert {i["key"]: i["state"] for i in r2["accessibility"]["items"]}["wheelchair_access"] == "documented"


def test_cfp_deadline_is_not_registration_deadline():
    n = TechConferencesAdapter().normalize(RawRecord("t", {"name": "TEST Conf", "url": "https://x.test.example", "startDate": "2030-01-01",
                                                           "cfpEndDate": "2029-10-01", "cfpUrl": "https://x.test.example/cfp"}))
    assert "registration_deadline" not in n.values
    assert n.extras["cfp"]["until"] == "2029-10-01"


# ----------------------------------------------------------- dedupe


def test_duplicate_by_url_across_sources_merges(db):
    a = FixtureAdapter("src_a", [rec("a1")], priority=60)
    b = FixtureAdapter("src_b", [rec("b1", title="Alpha Summit (renamed)", url="http://www.alpha.test.example/summit/?utm_source=x")], priority=50)
    ingest(db, a)
    install(a, b)
    ingest(db, b)
    assert db.scalar(select(__import__("sqlalchemy").func.count()).select_from(Event)) == 1
    ev = db.scalars(select(Event)).one()
    assert db.scalar(select(__import__("sqlalchemy").func.count()).select_from(SourceRecord).where(SourceRecord.event_id == ev.id)) == 2
    assert ev.title == "Test Summit Alpha"  # higher priority source wins the field


def test_duplicate_by_title_and_date_merges(db):
    ingest(db, FixtureAdapter("src_a", [rec("a1", url=None)]))
    ingest(db, FixtureAdapter("src_b", [rec("b1", url=None, title="The Test Summit Alpha 2030 Edition")]))
    assert len(db.scalars(select(Event)).all()) == 1


def test_duplicate_by_external_id_same_source_updates_not_duplicates(db):
    ad = FixtureAdapter("src_a", [rec("same")])
    ingest(db, ad)
    ad.records[0]["city"] = "Delhi"
    ingest(db, ad)
    assert len(db.scalars(select(Event)).all()) == 1
    assert len(db.scalars(select(SourceRecord)).all()) == 1


def test_same_title_same_date_different_city_not_merged(db):
    ingest(db, FixtureAdapter("src_a", [rec("a1", url=None, city="Pune")]))
    ingest(db, FixtureAdapter("src_b", [rec("b1", url=None, city="Delhi")]))
    assert len(db.scalars(select(Event)).all()) == 2
    cand = db.scalars(select(DuplicateCandidate)).all()
    assert len(cand) == 1 and "different location" in cand[0].reasons[0]


def test_same_url_different_dates_is_not_silently_merged(db):
    ingest(db, FixtureAdapter("src_a", [rec("a1")]))
    ingest(db, FixtureAdapter("src_b", [rec("b1", start=days(400).isoformat(), end=days(401).isoformat())]))
    assert len(db.scalars(select(Event)).all()) == 2
    assert len(db.scalars(select(DuplicateCandidate)).all()) == 1


def test_similar_but_different_events_not_merged(db):
    ingest(db, FixtureAdapter("src_a", [rec("a1", url=None, title="Test Hackathon Pune Beginners Track")]))
    ingest(db, FixtureAdapter("src_b", [rec("b1", url=None, title="Test Hackathon Pune Advanced Track", city="Pune")]))
    assert len(db.scalars(select(Event)).all()) == 2


def test_norm_title_strips_years_and_ordinals():
    assert norm_title("The 5th Annual Summit 2030 Edition!") == "annual summit"


# ----------------------------------------------------------- refresh, provenance, versions


def test_refresh_preserves_provenance_and_writes_versions(db):
    ad = FixtureAdapter("src_a", [rec("a1")])
    (ev,) = ingest(db, ad)
    v1 = db.scalars(select(EventVersion).where(EventVersion.event_id == ev.id)).all()
    assert [v.version_no for v in v1] == [1] and v1[0].summary == "Initial record created."
    ad.records[0].update(city="Delhi", start=days(45).isoformat(), end=days(46).isoformat())
    ingest(db, ad)
    db.expire_all()
    ev = db.get(Event, ev.id)
    assert ev.city == "Delhi"
    versions = db.scalars(select(EventVersion).where(EventVersion.event_id == ev.id).order_by(EventVersion.version_no)).all()
    assert [v.version_no for v in versions] == [1, 2]
    assert versions[1].diff["city"] == ["Pune", "Delhi"]
    assert versions[1].is_material and versions[1].change_source == "src_a"
    # raw record kept verbatim, assertions record the superseded value
    rec_row = db.scalars(select(SourceRecord)).one()
    assert rec_row.raw["city"] == "Delhi" and rec_row.source_url.startswith("https://src_a.test.example")
    city = db.scalars(select(EventFieldAssertion).where(EventFieldAssertion.event_id == ev.id, EventFieldAssertion.field_name == "city")).all()
    assert {json.loads(a.value): a.is_current for a in city} == {"Pune": False, "Delhi": True}
    assert all(a.source_id is not None and a.source_record_id is not None for a in city)


def test_unchanged_refresh_creates_no_version(db):
    ad = FixtureAdapter("src_a", [rec("a1")])
    (ev,) = ingest(db, ad)
    ingest(db, ad)
    assert db.query(EventVersion).filter_by(event_id=ev.id).count() == 1


def test_field_dropped_by_source_returns_to_unknown(db):
    ad = FixtureAdapter("src_a", [rec("a1", fee=300)])
    (ev,) = ingest(db, ad)
    assert ev.fee_status == "paid"
    del ad.records[0]["fee"]
    ingest(db, ad)
    db.expire_all()
    ev = db.get(Event, ev.id)
    assert ev.fee_status == "unknown" and ev.fee_amount is None


def test_conflicting_sources_are_exposed_not_dropped(db, client):
    ingest(db, FixtureAdapter("src_a", [rec("a1", city="Pune")], priority=60))
    ingest(db, FixtureAdapter("src_b", [rec("b1", city="Pune", venue=None)], priority=50))
    ad_c = FixtureAdapter("src_c", [rec("c1", city="Mumbai")], priority=10)
    (ev,) = db.scalars(select(Event)).all()
    # same URL + same dates merges; the lower-priority city disagrees and shows as a conflict
    ingest(db, ad_c)
    r = client.get(f"/api/events/{ev.id}").json()
    db.expire_all()
    assert db.get(Event, ev.id).city == "Pune"  # higher-priority source wins
    conflicts = {c["field"] for c in r["provenance"]["conflicts"]}
    assert "city" in conflicts


# ----------------------------------------------------------- stale / expiry / cancellation


def test_missing_from_source_is_removed_not_cancelled(db):
    ad = FixtureAdapter("src_a", [rec("a1")])
    (ev,) = ingest(db, ad)
    src = source_row(db, ad)
    n = mark_missing_records(db, src, seen_ids=set(), documents={"fixture-doc"})
    db.commit()
    db.expire_all()
    ev = db.get(Event, ev.id)
    assert n == 1 and ev.lifecycle_status == "removed_from_source" and ev.lifecycle_status != "cancelled"
    # source lists it again -> restored
    ingest(db, ad)
    db.expire_all()
    assert db.get(Event, ev.id).lifecycle_status == "scheduled"


def test_explicit_cancellation_from_source(db):
    (ev,) = ingest(db, FixtureAdapter("src_a", [rec("a1", lifecycle="cancelled")]))
    assert ev.lifecycle_status == "cancelled"


def test_removed_cancelled_and_past_events_hidden_from_default_search(db, client):
    ingest(db, FixtureAdapter("src_a", [rec("1", title="Live Event", url=None), rec("2", title="Cancelled Event", url=None, lifecycle="cancelled", start=days(5).isoformat(), end=days(6).isoformat()),
                                         rec("3", title="Past Event", url=None, start=days(-30).isoformat(), end=days(-29).isoformat())]))
    titles = {i["title"] for i in client.get("/api/events").json()["items"]}
    assert titles == {"Live Event"}
    past = {i["title"] for i in client.get("/api/events?include_past=true").json()["items"]}
    assert "Past Event" in past


def test_stale_data_flagged_by_freshness(db, client):
    (ev,) = ingest(db, FixtureAdapter("src_a", [rec("a1")]))
    db.query(Event).filter_by(id=ev.id).update({"last_refreshed_at": datetime.now(UTC) - timedelta(days=60)})
    db.commit()
    card = client.get("/api/events").json()["items"][0]
    assert card["freshness"]["state"] == "stale" and card["freshness"]["age_days"] >= 60
    fresh_ev = ingest(db, FixtureAdapter("src_b", [rec("b", title="Other Fresh", url=None, start=days(90).isoformat())]))[0]
    items = {i["id"]: i for i in client.get("/api/events").json()["items"]}
    assert items[str(fresh_ev.id)]["freshness"]["state"] == "fresh"
