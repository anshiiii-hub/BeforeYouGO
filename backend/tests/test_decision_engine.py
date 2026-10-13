"""Decision engine: hard constraints, budget with unknown costs, explanation fidelity, profile-specific ranking."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from app.models import Event, StudentProfile
from app.services.scoring import DEFAULT_WEIGHTS, suitability
from tests.support.factories import auth, days, make_event, make_profile, make_user


def ev(**kw):
    base = dict(title="Test Event", description="", prerequisites=None, eligibility=None, tags_text=None, topics=[], category="hackathon",
                format="offline", city="Delhi", start_date=days(30), end_date=days(31), fee_status="unknown", fee_amount=None, fee_currency=None,
                lifecycle_status="scheduled", registration_deadline=None, eligibility_structured={}, offers_certificate=None, offers_mentorship=None)
    base.update(kw)
    return Event(**base)


def prof(**kw):
    base = dict(interests=[], preferred_formats=[], accessibility_needs=[], require_format=False)
    base.update(kw)
    return StudentProfile(**base)


def keys(result):
    return {v["key"] for v in result["hard_violations"]}


# ----------------------------------------------------------- hard constraints


def test_eligibility_year_blocks_high_fit_even_with_perfect_interest():
    e = ev(eligibility="Open only to second year students.", topics=["ai", "ml"], title="AI ML Hackathon", fee_status="free")
    p = prof(year_of_study=4, interests=["ai", "machine learning"], max_budget_inr=1000, skill_level="beginner")
    r = suitability(e, p)
    assert not r["eligible"] and "eligibility" in keys(r)
    assert r["label"] == "Excluded by your constraints"
    assert any("year 4" in m for m in r["why_skip"])
    ok = suitability(e, prof(year_of_study=2, interests=["ai", "machine learning"]))
    assert ok["eligible"] and ok["label"] != "Excluded by your constraints"


def test_eligibility_unknown_year_asks_student_instead_of_guessing():
    r = suitability(ev(eligibility="Open only to second year students."), prof())
    assert r["eligible"] and any(u["key"] == "eligibility" for u in r["unknowns"])


def test_education_level_constraint():
    r = suitability(ev(eligibility="Open to postgraduate students only."), prof(education_level="undergraduate"))
    assert "eligibility_level" in keys(r)


def test_ended_cancelled_and_closed_registration_excluded():
    now = datetime.now(UTC)
    assert "event_ended" in keys(suitability(ev(start_date=days(-10), end_date=days(-9)), prof()))
    assert "cancelled" in keys(suitability(ev(lifecycle_status="cancelled"), prof()))
    assert "registration_closed" in keys(suitability(ev(registration_deadline=now - timedelta(days=1)), prof()))
    assert suitability(ev(registration_deadline=now + timedelta(days=2)), prof())["eligible"]


def test_required_format_schedule_travel_and_access_are_hard():
    assert "format" in keys(suitability(ev(format="online"), prof(require_format=True, preferred_formats=["offline"])))
    assert "format" not in keys(suitability(ev(format="hybrid"), prof(require_format=True, preferred_formats=["offline"])))
    assert "schedule" in keys(suitability(ev(), prof(available_from=days(60))))
    assert "travel" in keys(suitability(ev(city="Chennai"), prof(home_city="Delhi", max_travel_km=300)))
    r = suitability(ev(), prof(accessibility_needs=["wheelchair_access"]), access={"wheelchair_access": "confirmed_unavailable"})
    assert "access_wheelchair_access" in keys(r)
    r2 = suitability(ev(), prof(accessibility_needs=["wheelchair_access"]))  # not documented -> unknown, never a violation
    assert r2["eligible"] and any(u["key"] == "access_wheelchair_access" and "unknown, not unavailable" in u["message"] for u in r2["unknowns"])


def test_soft_preferences_are_not_hard_constraints():
    r = suitability(ev(format="online"), prof(preferred_formats=["offline"], require_format=False))
    assert r["eligible"]


# ----------------------------------------------------------- budget


def comp(r, key):
    return next(c for c in r["components"] if c["key"] == key)


def test_budget_over_known_fee_excluded_within_budget_scored():
    assert "budget" in keys(suitability(ev(fee_status="paid", fee_amount=Decimal(900), fee_currency="INR"), prof(max_budget_inr=500)))
    r = suitability(ev(fee_status="paid", fee_amount=Decimal(100), fee_currency="INR"), prof(max_budget_inr=500))
    assert r["eligible"] and comp(r, "budget")["score"] == 1.0
    r = suitability(ev(fee_status="paid", fee_amount=Decimal(400), fee_currency="INR"), prof(max_budget_inr=500))
    assert comp(r, "budget")["score"] == 0.75


def test_unknown_fee_is_not_free_not_scored_and_flagged():
    r = suitability(ev(fee_status="unknown"), prof(max_budget_inr=500))
    b = comp(r, "budget")
    assert b["known"] is False and b["score"] is None and b["contribution"] is None
    assert "unknown" in b["reason"].lower()
    assert any(u["key"] == "budget" and "not stated" in u["message"] for u in r["unknowns"])
    free = suitability(ev(fee_status="free"), prof(max_budget_inr=500))
    assert comp(free, "budget")["score"] == 1.0 and not any(u["key"] == "budget" for u in free["unknowns"])


def test_paid_without_amount_is_flagged_as_unknown_cost():
    r = suitability(ev(fee_status="paid", fee_amount=None), prof(max_budget_inr=500))
    assert comp(r, "budget")["score"] is None
    assert any(u["key"] == "budget" for u in r["unknowns"])


def test_foreign_currency_not_converted():
    r = suitability(ev(fee_status="paid", fee_amount=Decimal(5), fee_currency="USD"), prof(max_budget_inr=1))
    assert r["eligible"] and any(u["key"] == "budget" and "not converted" in u["message"] for u in r["unknowns"])


def test_unknown_cost_not_rewarded_over_known_cheap():
    p = prof(max_budget_inr=500, interests=["ai"])
    unknown = suitability(ev(fee_status="unknown", topics=["ai"]), p)
    known = suitability(ev(fee_status="free", topics=["ai"]), p)
    assert known["score"] >= unknown["score"]


# ----------------------------------------------------------- explanation == numbers


def test_explanation_matches_component_scores_and_weights():
    e = ev(fee_status="paid", fee_amount=Decimal(100), fee_currency="INR", topics=["ai"], format="online", title="AI Online Event")
    p = prof(max_budget_inr=500, interests=["ai"], preferred_formats=["online"])
    r = suitability(e, p)
    known = [c for c in r["components"] if c["known"]]
    assert {c["key"] for c in known} == {"interest", "budget", "location", "format"}
    kw = sum(c["weight"] for c in known)
    expected = round(100 * sum(c["weight"] * c["score"] for c in known) / kw)
    assert abs(r["score"] - expected) <= 1
    assert abs(sum(c["contribution"] for c in known) - r["score"]) <= 1.0
    total_w = sum(c["weight"] for c in r["components"])
    assert r["coverage"] == round(kw / total_w, 2)
    assert f"Based on {len(known)} of {len(r['components'])} factors ({round(r['coverage'] * 100)}% of the weight)" in r["note"]
    for c in r["components"]:
        assert c["weight"] == round(DEFAULT_WEIGHTS[c["key"]], 3)
    # reason text states the very numbers used
    assert "Fee ₹100" in comp(r, "budget")["reason"] and "₹500" in comp(r, "budget")["reason"]
    assert "ai" in comp(r, "interest")["reason"]
    assert set(r["why_match"]) == {c["reason"] for c in known if c["score"] >= 0.7}


def test_custom_weights_change_score_and_are_reported():
    e = ev(fee_status="paid", fee_amount=Decimal(900), fee_currency="INR", topics=["ai"])
    p = prof(interests=["ai"], max_budget_inr=1000)
    base = suitability(e, p)
    heavy = suitability(e, p, weights={**DEFAULT_WEIGHTS, "interest": 0.9, "budget": 0.01})
    kn = [c for c in heavy["components"] if c["known"]]
    assert abs(heavy["score"] - round(100 * sum(c["weight"] * c["score"] for c in kn) / sum(c["weight"] for c in kn))) <= 1
    assert base["weights"] == DEFAULT_WEIGHTS
    assert comp(heavy, "interest")["weight"] == 0.9 and heavy["weights"]["interest"] == 0.9


def test_tradeoffs_and_weak_reasons_come_from_components():
    e = ev(topics=["web"], fee_status="free", title="Web Event")
    r = suitability(e, prof(interests=["ai"], max_budget_inr=100))
    weak = comp(r, "interest")
    assert weak["score"] == 0.15 and weak["reason"] in r["why_skip"]
    assert r["tradeoffs"] and "Budget" in r["tradeoffs"][0] and "interest alignment" in r["tradeoffs"][0]


def test_low_coverage_is_not_rated():
    r = suitability(ev(format="unknown"), prof())
    assert r["label"] == "Not enough information to rate"


def test_no_profile_gives_no_score():
    r = suitability(ev(), None)
    assert r["score"] is None and r["components"] == []


# ----------------------------------------------------------- different profiles -> different rankings (API)


def test_different_profiles_get_different_rankings(db, client):
    ai = make_event(db, "AI Summit Pune", topics=["ai", "ml"], category="conference", format="online", fee_status="free", start_date=days(20), end_date=days(21))
    sec = make_event(db, "Security CTF Night", topics=["security"], category="competition", format="online", fee_status="free", start_date=days(21), end_date=days(22))
    web = make_event(db, "Web Dev Day", topics=["web"], category="meetup", format="online", fee_status="free", start_date=days(22), end_date=days(23))
    u1, u2 = make_user(db), make_user(db)
    make_profile(db, u1, interests=["ai"], preferred_formats=["online"], max_budget_inr=Decimal(100))
    make_profile(db, u2, interests=["security"], preferred_formats=["online"], max_budget_inr=Decimal(100))
    r1 = client.get("/api/me/recommendations", headers=auth(u1)).json()
    r2 = client.get("/api/me/recommendations", headers=auth(u2)).json()
    t1 = [i["title"] for i in r1["items"]]
    t2 = [i["title"] for i in r2["items"]]
    assert t1[0] == "AI Summit Pune" and t2[0] == "Security CTF Night" and t1 != t2
    assert {ai.id, sec.id, web.id} and len(t1) == 3
    top = r1["items"][0]
    assert top["fit"]["components"] and top["why_match"] and "weighted" in r1["method"]


def test_recommendations_exclude_ineligible_and_explain_why(db, client):
    make_event(db, "Final Year Only Hackathon", eligibility="Open only to final year students.", topics=["ai"], format="online", start_date=days(10), end_date=days(11))
    make_event(db, "Open AI Meetup", topics=["ai"], format="online", fee_status="free", start_date=days(12), end_date=days(12))
    u = make_user(db)
    make_profile(db, u, interests=["ai"], year_of_study=1, preferred_formats=["online"])
    r = client.get("/api/me/recommendations", headers=auth(u)).json()
    assert [i["title"] for i in r["items"]] == ["Open AI Meetup"]
    assert r["excluded"]["count"] == 1 and r["excluded"]["reasons"][0]["key"] == "eligibility"
    assert "year 1" in r["excluded"]["examples"][0]["why"][0]


def test_recommendations_need_profile(db, client):
    u = make_user(db)
    assert client.get("/api/me/recommendations", headers=auth(u)).json()["needs_profile"] is True
