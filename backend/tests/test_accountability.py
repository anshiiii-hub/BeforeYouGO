"""Accountability: claim lifecycle, evidence rules, authorisation, disputes, participant outcomes, audit trail."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError, IntegrityError

from app.domain.enums import ClaimStatus
from app.models import AuditLog, Claim, ClaimStatusHistory, Evidence, FeedbackResponse
from tests.support.factories import (
    auth,
    days,
    make_claim,
    make_event,
    make_evidence,
    make_feedback,
    make_org,
    make_participation,
    make_user,
)

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64


@pytest.fixture
def w(db):
    """A finished event owned by org A, one advertised prize claim, and one user per role."""
    org_user = make_user(db, "organizer")
    other_org_user = make_user(db, "organizer")
    org = make_org(db, org_user)
    make_org(db, other_org_user)
    ev = make_event(db, "Ended Hackathon", owner_org_id=org.id, start_date=days(-20), end_date=days(-15), category="hackathon")
    claim = make_claim(db, ev, "Winners receive a cash prize of Rs 50000.")
    return SimpleNamespace(org=org, ev=ev, claim=claim, organizer=org_user, other_org=other_org_user, reviewer=make_user(db, "reviewer"),
                           admin=make_user(db, "admin"), student=make_user(db, "student"), db=db)


def move(client, w, user, to, reason="Because the rules require a reason.", claim=None):
    return client.post(f"/api/claims/{(claim or w.claim).id}/transition", json={"to_status": to, "reason": reason}, headers=auth(user) if user else {})


def status(w, claim=None):
    w.db.expire_all()
    return w.db.get(Claim, (claim or w.claim).id).status


def set_status(w, to, claim=None):
    c = w.db.get(Claim, (claim or w.claim).id)
    c.status = to
    w.db.commit()


# ----------------------------------------------------------- lifecycle transitions


def test_valid_transition_records_full_history_and_audit(w, client):
    r = move(client, w, w.reviewer, "needs_clarification", "Prize amount is ambiguous.")
    assert r.status_code == 200 and r.json()["status"] == "needs_clarification"
    w.db.expire_all()
    rows = w.db.scalars(select(ClaimStatusHistory).where(ClaimStatusHistory.claim_id == w.claim.id).order_by(ClaimStatusHistory.created_at)).all()
    assert len(rows) == 2
    h = rows[-1]
    assert (h.actor_id, h.actor_role, h.from_status, h.to_status, h.reason) == (w.reviewer.id, "reviewer", "advertised", "needs_clarification", "Prize amount is ambiguous.")
    assert h.created_at is not None and h.evidence_ids == []
    a = w.db.scalars(select(AuditLog).where(AuditLog.action == "claim.status_changed")).one()
    assert a.actor_id == w.reviewer.id and a.actor_role == "reviewer" and a.target_id == str(w.claim.id) and a.created_at is not None
    assert a.details["from"] == "advertised" and a.details["to"] == "needs_clarification" and a.details["reason"] == "Prize amount is ambiguous."


def test_history_records_evidence_ids(w, client):
    ev = make_evidence(w.db, w.claim, kind="organizer_provided", submitted_by=w.organizer)
    assert move(client, w, w.organizer, "evidence_submitted").status_code == 200
    w.db.expire_all()
    h = w.db.scalars(select(ClaimStatusHistory).where(ClaimStatusHistory.to_status == "evidence_submitted")).one()
    assert h.evidence_ids == [str(ev.id)]


@pytest.mark.parametrize("start,to", [("advertised", "fulfilled"), ("advertised", "corroborated"), ("fulfilled", "advertised"),
                                      ("needs_clarification", "fulfilled"), ("unverified", "fulfilled"), ("advertised", "advertised")])
def test_invalid_transitions_rejected(w, client, start, to):
    set_status(w, start)
    r = move(client, w, w.admin, to)
    assert r.status_code == 422 and r.json()["error"]["code"] == "invalid_transition"
    assert status(w) == start


def test_reason_required(w, client):
    r = move(client, w, w.reviewer, "needs_clarification", reason="   ")
    assert r.status_code == 422
    assert status(w) == "advertised"


def test_evidence_submitted_requires_attached_evidence(w, client):
    r = move(client, w, w.organizer, "evidence_submitted")
    assert r.status_code == 422 and r.json()["error"]["code"] == "evidence_requirements_not_met"
    assert "Attach at least one evidence" in r.json()["error"]["details"][0]
    make_evidence(w.db, w.claim, kind="organizer_provided", review_status="rejected", submitted_by=w.organizer)
    assert move(client, w, w.organizer, "evidence_submitted").status_code == 422  # rejected evidence does not count
    make_evidence(w.db, w.claim, kind="organizer_provided", submitted_by=w.organizer)
    assert move(client, w, w.organizer, "evidence_submitted").status_code == 200


def test_organizer_evidence_alone_cannot_corroborate_or_fulfil(w, client):
    make_evidence(w.db, w.claim, kind="organizer_provided", review_status="accepted", submitted_by=w.organizer)
    set_status(w, "evidence_submitted")
    for to in ("corroborated", "fulfilled", "partially_fulfilled"):
        r = move(client, w, w.reviewer, to)
        assert r.status_code == 422 and r.json()["error"]["code"] == "evidence_requirements_not_met", to
    assert status(w) == "evidence_submitted"


def test_independent_accepted_evidence_allows_corroboration_then_fulfilment(w, client):
    ev = make_evidence(w.db, w.claim, kind="public_source", review_status="pending")
    set_status(w, "evidence_submitted")
    assert move(client, w, w.reviewer, "corroborated").status_code == 422  # pending is not accepted
    r = client.post(f"/api/evidence/{ev.id}/review", json={"decision": "accepted", "note": "Verified on the public page."}, headers=auth(w.reviewer))
    assert r.status_code == 200 and r.json()["review_status"] == "accepted"
    assert move(client, w, w.reviewer, "corroborated").status_code == 200
    assert move(client, w, w.reviewer, "fulfilled").status_code == 200
    assert status(w) == "fulfilled"


def test_non_claim_specific_evidence_is_not_enough(w, client):
    make_evidence(w.db, w.claim, kind="public_source", review_status="accepted", claim_specific=False)
    set_status(w, "evidence_submitted")
    assert move(client, w, w.reviewer, "corroborated").status_code == 422


def test_fulfilment_requires_event_to_have_ended(w, client):
    ev = make_event(w.db, "Future Event", owner_org_id=w.org.id, start_date=days(10), end_date=days(11))
    c = make_claim(w.db, ev, "Mentors will be assigned to every team.", status="evidence_submitted")
    make_evidence(w.db, c, kind="public_source", review_status="accepted")
    r = move(client, w, w.reviewer, "fulfilled", claim=c)
    assert r.status_code == 422 and "has not ended" in r.json()["error"]["details"][0]


def test_participant_confirmations_threshold_and_rules(w, client):
    set_status(w, "evidence_submitted")
    make_evidence(w.db, w.claim, kind="organizer_provided", submitted_by=w.organizer)
    users = [make_user(w.db) for _ in range(4)]
    for u in users[:2]:
        make_participation(w.db, u, w.ev)
        make_feedback(w.db, u, w.claim, "delivered", "published")
    assert move(client, w, w.reviewer, "fulfilled").status_code == 422          # 2 < threshold 3
    make_participation(w.db, users[2], w.ev, coi=True)                           # conflict of interest: shown but never counted
    make_feedback(w.db, users[2], w.claim, "delivered", "published")
    make_participation(w.db, users[3], w.ev)
    make_feedback(w.db, users[3], w.claim, "delivered", "pending")               # unmoderated: not counted
    assert move(client, w, w.reviewer, "fulfilled").status_code == 422
    w.db.query(FeedbackResponse).filter_by(user_id=users[3].id).update({"status": "published"})
    w.db.commit()
    r = move(client, w, w.reviewer, "fulfilled")
    assert r.status_code == 200 and status(w) == "fulfilled"


def test_unverified_means_no_evidence_not_misconduct(w, client):
    recent = make_event(w.db, "Just Ended", owner_org_id=w.org.id, start_date=days(-3), end_date=days(-2))
    c_recent = make_claim(w.db, recent, "Certificates will be issued to all participants.")
    r = move(client, w, w.reviewer, "unverified", claim=c_recent)
    assert r.status_code == 422 and "Wait at least 14 days" in r.json()["error"]["details"][0]
    r = move(client, w, w.reviewer, "unverified", "No qualifying evidence found after the grace period.")
    assert r.status_code == 200
    body = r.json()
    assert "not a finding that the promise was broken" in body["status_note"]
    desc = next(t for t in body["transitions"] if t["to"] == "evidence_submitted")  # can still be reopened with new evidence
    assert desc
    bad_words = ("broken", "false", "fraud", "fake", "misconduct", "lie")
    assert not [s for s in ClaimStatus if any(b in s.value for b in bad_words)]


def test_unverified_blocked_if_qualifying_evidence_exists(w, client):
    make_evidence(w.db, w.claim, kind="independent_review", review_status="accepted")
    r = move(client, w, w.reviewer, "unverified")
    assert r.status_code == 422 and "Qualifying evidence exists" in r.json()["error"]["details"][-1]


def test_history_and_audit_tables_are_append_only(w, client):
    move(client, w, w.reviewer, "needs_clarification")
    for sql in ("UPDATE claim_status_history SET reason='tampered'", "DELETE FROM claim_status_history",
                "UPDATE audit_logs SET action='tampered'", "DELETE FROM audit_logs"):
        with pytest.raises((DBAPIError, IntegrityError)) as e:
            w.db.execute(text(sql))
        assert "append-only" in str(e.value)
        w.db.rollback()


# ----------------------------------------------------------- authorisation


@pytest.mark.parametrize("who,code", [(None, 401), ("student", 403), ("other_org", 403)])
def test_unauthorised_users_cannot_change_claim_status(w, client, who, code):
    make_evidence(w.db, w.claim, kind="organizer_provided", submitted_by=w.organizer)
    user = getattr(w, who) if who else None
    r = move(client, w, user, "evidence_submitted")
    assert r.status_code == code
    if who == "other_org":
        assert r.json()["error"]["code"] == "not_event_owner"
    assert status(w) == "advertised"
    for to in ("needs_clarification", "disputed", "unable_to_determine"):
        if who:
            assert move(client, w, getattr(w, who), to).status_code == 403
    assert status(w) == "advertised"


def test_organizer_cannot_establish_outcomes_on_own_claim(w, client):
    set_status(w, "evidence_submitted")
    make_evidence(w.db, w.claim, kind="public_source", review_status="accepted")
    for to in ("corroborated", "fulfilled", "unverified", "unable_to_determine"):
        r = move(client, w, w.organizer, to)
        assert r.status_code == 403 and r.json()["error"]["code"] == "transition_forbidden"
    assert status(w) == "evidence_submitted"


@pytest.mark.parametrize("who,code", [(None, 401), ("student", 403), ("organizer", 403), ("other_org", 403)])
def test_only_reviewers_can_review_evidence(w, client, who, code):
    ev = make_evidence(w.db, w.claim, kind="public_source")
    r = client.post(f"/api/evidence/{ev.id}/review", json={"decision": "accepted", "note": "Looks right to me."}, headers=auth(getattr(w, who)) if who else {})
    assert r.status_code == code
    w.db.expire_all()
    assert w.db.get(Evidence, ev.id).review_status == "pending"


def test_reviewer_in_owning_org_has_conflict_of_interest(w, client):
    from app.models import OrganizationMember

    w.db.add(OrganizationMember(organization_id=w.org.id, user_id=w.reviewer.id))
    w.db.commit()
    ev = make_evidence(w.db, w.claim, kind="public_source")
    assert move(client, w, w.reviewer, "needs_clarification").json()["error"]["code"] == "conflict_of_interest"
    r = client.post(f"/api/evidence/{ev.id}/review", json={"decision": "accepted", "note": "I work here, but fine."}, headers=auth(w.reviewer))
    assert r.status_code == 403 and r.json()["error"]["code"] == "conflict_of_interest"


def test_reviewer_cannot_review_own_evidence(w, client):
    r = client.post(f"/api/claims/{w.claim.id}/evidence", json={"url": "https://pub.test.example/x"}, headers=auth(w.reviewer))
    assert r.status_code == 201 and r.json()["kind"] == "independent_review"
    r2 = client.post(f"/api/evidence/{r.json()['id']}/review", json={"decision": "accepted", "note": "Self approval."}, headers=auth(w.reviewer))
    assert r2.status_code == 403 and r2.json()["error"]["code"] == "self_review"


# ----------------------------------------------------------- evidence submission + poster upload


def test_organizer_evidence_is_always_labelled_organizer_provided(w, client):
    r = client.post(f"/api/claims/{w.claim.id}/evidence", json={"url": "https://us.test.example/proof", "kind": "independent_review"}, headers=auth(w.organizer))
    assert r.status_code == 201 and r.json()["kind"] == "organizer_provided" and r.json()["review_status"] == "pending"
    other = client.post(f"/api/claims/{w.claim.id}/evidence", json={"url": "https://us.test.example/proof"}, headers=auth(w.other_org))
    assert other.status_code == 403


def test_organizer_poster_upload_cannot_make_prize_claim_fulfilled(w, client, upload_dir):
    r = client.post(f"/api/claims/{w.claim.id}/evidence/upload", files={"file": ("poster.png", PNG, "image/png")}, data={"excerpt": "Prize poster", "kind": "public_source"},
                    headers=auth(w.organizer))
    assert r.status_code == 201
    ev = r.json()
    assert ev["kind"] == "organizer_provided" and ev["has_file"] and ev["mime_type"] == "image/png"
    assert (upload_dir / str(w.ev.id)).exists()
    assert status(w) == "advertised"
    assert move(client, w, w.organizer, "evidence_submitted").status_code == 200
    # even after a reviewer accepts the poster itself
    assert client.post(f"/api/evidence/{ev['id']}/review", json={"decision": "accepted", "note": "Poster is genuine."}, headers=auth(w.reviewer)).status_code == 200
    for to in ("fulfilled", "corroborated"):
        r = move(client, w, w.reviewer, to)
        assert r.status_code == 422 and r.json()["error"]["code"] == "evidence_requirements_not_met"
    assert move(client, w, w.organizer, "fulfilled").status_code == 403
    assert status(w) == "evidence_submitted"


def test_student_needs_participation_to_report_and_report_is_participant_kind(w, client):
    r = client.post(f"/api/claims/{w.claim.id}/evidence", json={"excerpt": "We received the prize."}, headers=auth(w.student))
    assert r.status_code == 403 and r.json()["error"]["code"] == "not_a_participant"
    make_participation(w.db, w.student, w.ev)
    r = client.post(f"/api/claims/{w.claim.id}/evidence", json={"excerpt": "We received the prize.", "kind": "independent_review"}, headers=auth(w.student))
    assert r.status_code == 201 and r.json()["kind"] == "participant_report" and r.json()["kind_label"] == "Participant report"


def test_evidence_requires_some_content_and_safe_url(w, client):
    assert client.post(f"/api/claims/{w.claim.id}/evidence", json={}, headers=auth(w.organizer)).json()["error"]["code"] == "evidence_empty"
    r = client.post(f"/api/claims/{w.claim.id}/evidence", json={"url": "javascript:alert(1)"}, headers=auth(w.organizer))
    assert r.status_code == 422 and r.json()["error"]["code"] == "invalid_url"


# ----------------------------------------------------------- disputes


def test_dispute_preserves_original_history_and_restores_prior_status(w, client):
    set_status(w, "needs_clarification")
    original_text = w.claim.original_text
    r = client.post("/api/disputes", json={"event_id": str(w.ev.id), "claim_id": str(w.claim.id), "kind": "claim_dispute",
                                           "description": "We never promised this amount in writing."}, headers=auth(w.organizer))
    assert r.status_code == 201 and r.json()["prior_claim_status"] == "needs_clarification"
    assert status(w) == "disputed"
    w.db.expire_all()
    assert w.db.get(Claim, w.claim.id).original_text == original_text
    hist = w.db.scalars(select(ClaimStatusHistory).where(ClaimStatusHistory.claim_id == w.claim.id).order_by(ClaimStatusHistory.created_at)).all()
    assert [h.to_status for h in hist] == ["advertised", "disputed"]  # original row untouched, dispute appended
    assert hist[1].from_status == "needs_clarification" and hist[1].actor_role == "organizer"
    dup = client.post("/api/disputes", json={"event_id": str(w.ev.id), "claim_id": str(w.claim.id), "kind": "claim_dispute",
                                             "description": "Same dispute again for this claim."}, headers=auth(w.organizer))
    assert dup.status_code == 409
    res = client.post(f"/api/disputes/{r.json()['id']}/resolve", json={"outcome": "rejected", "note": "Brochure page 2 states it."}, headers=auth(w.reviewer))
    assert res.status_code == 200 and res.json()["status"] == "rejected"
    assert status(w) == "needs_clarification"
    w.db.expire_all()
    hist = w.db.scalars(select(ClaimStatusHistory).where(ClaimStatusHistory.claim_id == w.claim.id).order_by(ClaimStatusHistory.created_at)).all()
    assert [h.to_status for h in hist] == ["advertised", "disputed", "needs_clarification"]
    assert hist[2].review_outcome == "dispute_rejected" and hist[2].actor_role == "reviewer"
    assert client.post(f"/api/disputes/{r.json()['id']}/resolve", json={"outcome": "upheld", "note": "Changed my mind."}, headers=auth(w.reviewer)).status_code == 409


def test_withdrawn_claim_keeps_its_history(w, client):
    d = client.post("/api/disputes", json={"event_id": str(w.ev.id), "claim_id": str(w.claim.id), "kind": "claim_dispute",
                                           "description": "This sentence was extracted incorrectly."}, headers=auth(w.organizer)).json()
    r = client.post(f"/api/disputes/{d['id']}/resolve", json={"outcome": "upheld", "note": "Extraction error confirmed.", "withdraw_claim": True}, headers=auth(w.admin))
    assert r.status_code == 200
    w.db.expire_all()
    c = w.db.get(Claim, w.claim.id)
    assert c.is_active is False and c.original_text.startswith("Winners receive")
    assert w.db.scalars(select(ClaimStatusHistory).where(ClaimStatusHistory.claim_id == c.id)).all().__len__() == 3
    assert w.db.scalars(select(AuditLog).where(AuditLog.action == "claim.withdrawn")).one()


@pytest.mark.parametrize("who,code", [(None, 401), ("student", 403), ("reviewer", 403), ("other_org", 403)])
def test_only_owning_organizer_can_raise_dispute(w, client, who, code):
    r = client.post("/api/disputes", json={"event_id": str(w.ev.id), "claim_id": str(w.claim.id), "kind": "claim_dispute",
                                           "description": "I would like to dispute this claim."}, headers=auth(getattr(w, who)) if who else {})
    assert r.status_code == code and status(w) == "advertised"


@pytest.mark.parametrize("who,code", [(None, 401), ("student", 403), ("organizer", 403)])
def test_only_reviewers_resolve_disputes(w, client, who, code):
    d = client.post("/api/disputes", json={"event_id": str(w.ev.id), "claim_id": str(w.claim.id), "kind": "claim_dispute",
                                           "description": "We dispute this claim for reasons."}, headers=auth(w.organizer)).json()
    r = client.post(f"/api/disputes/{d['id']}/resolve", json={"outcome": "upheld", "note": "I decide myself."}, headers=auth(getattr(w, who)) if who else {})
    assert r.status_code == code and status(w) == "disputed"


# ----------------------------------------------------------- participant feedback and outcome summary


def outcomes(client, w):
    return client.get(f"/api/events/{w.ev.id}/outcomes").json()


def test_feedback_requires_participation_and_ended_event(w, client):
    body = {"items": [{"claim_id": str(w.claim.id), "response": "delivered"}]}
    assert client.post(f"/api/events/{w.ev.id}/feedback", json=body, headers=auth(w.student)).json()["error"]["code"] == "not_a_participant"
    assert client.post(f"/api/events/{w.ev.id}/feedback", json=body).status_code == 401
    live = make_event(w.db, "Live Now", start_date=days(-1), end_date=days(3))
    c = make_claim(w.db, live, "Food will be provided each day.", category="food")
    make_participation(w.db, w.student, live)
    r = client.post(f"/api/events/{live.id}/feedback", json={"items": [{"claim_id": str(c.id), "response": "delivered"}]}, headers=auth(w.student))
    assert r.status_code == 422 and r.json()["error"]["code"] == "event_not_ended"


def test_participation_cannot_be_declared_before_event_starts(w, client):
    future = make_event(w.db, "Future", start_date=days(5), end_date=days(6))
    r = client.post(f"/api/me/participations/{future.id}", json={}, headers=auth(w.student))
    assert r.status_code == 422 and r.json()["error"]["code"] == "event_not_started"
    assert client.post(f"/api/me/participations/{w.ev.id}", json={}, headers=auth(w.student)).status_code == 200


def test_feedback_stored_pending_and_duplicate_blocked(w, client):
    make_participation(w.db, w.student, w.ev)
    body = {"items": [{"claim_id": str(w.claim.id), "response": "delivered", "comment": "Got it."}]}
    r = client.post(f"/api/events/{w.ev.id}/feedback", json=body, headers=auth(w.student))
    assert r.status_code == 201 and r.json()["saved"] == 1
    w.db.expire_all()
    fb = w.db.scalars(select(FeedbackResponse)).one()
    assert fb.status == "pending" and fb.response == "delivered" and fb.user_id == w.student.id and fb.participation_level == "self_declared"
    again = client.post(f"/api/events/{w.ev.id}/feedback", json=body, headers=auth(w.student))
    assert again.status_code == 409 and again.json()["error"]["code"] == "nothing_saved"
    twice = client.post(f"/api/events/{w.ev.id}/feedback", json={"items": body["items"] * 2}, headers=auth(make_user(w.db)))
    assert twice.status_code == 403  # not a participant
    assert len(w.db.scalars(select(FeedbackResponse)).all()) == 1
    with pytest.raises(IntegrityError):  # the database enforces it too
        w.db.add(FeedbackResponse(event_id=w.ev.id, claim_id=w.claim.id, user_id=w.student.id, participation_level="self_declared", response="not_delivered"))
        w.db.commit()
    w.db.rollback()


def test_same_claim_twice_in_one_submission_counts_once(w, client):
    make_participation(w.db, w.student, w.ev)
    item = {"claim_id": str(w.claim.id), "response": "delivered"}
    r = client.post(f"/api/events/{w.ev.id}/feedback", json={"items": [item, {**item, "response": "not_delivered"}]}, headers=auth(w.student))
    assert r.json()["saved"] == 1 and r.json()["skipped"][0]["reason"] == "listed twice in this submission"


def test_insufficient_evidence_below_minimum_responses(w, client):
    users = [make_user(w.db) for _ in range(3)]
    for u in users[:2]:
        make_participation(w.db, u, w.ev)
        make_feedback(w.db, u, w.claim, "delivered", "published")
    make_participation(w.db, users[2], w.ev)
    make_feedback(w.db, users[2], w.claim, "delivered", "pending")  # unmoderated responses never count
    o = outcomes(client, w)
    c = o["claims"][0]
    assert c["verdict"] == "insufficient_evidence" and c["responses_total"] == 2 and o["min_responses_required"] == 3
    assert "Insufficient evidence" in c["summary"] and "(at least 3 needed)" in c["summary"]
    assert o["participants_declared"] == 3 and o["response_rate"] == {"numerator": 3, "denominator": 3, "pct": 100}
    w.db.query(FeedbackResponse).filter_by(user_id=users[2].id).update({"status": "published"})
    w.db.commit()
    c = outcomes(client, w)["claims"][0]
    assert c["verdict"] == "participants_report_delivered" and "not independently verified" in c["summary"]


def test_participant_reports_are_distinct_from_verified_outcomes(w, client):
    u = make_user(w.db)
    make_participation(w.db, u, w.ev)
    make_evidence(w.db, w.claim, kind="participant_report", review_status="accepted", submitted_by=u)
    c = outcomes(client, w)["claims"][0]
    assert c["independent_evidence_accepted"] == 0 and c["verdict"] == "insufficient_evidence"
    assert c["status"] == "advertised"  # a participant report never changes verified status
    make_evidence(w.db, w.claim, kind="independent_review", review_status="accepted")
    c = outcomes(client, w)["claims"][0]
    assert c["independent_evidence_accepted"] == 1 and c["verdict"] != "insufficient_evidence"
    assert c["evidence"]["participant_report:accepted"] == 1 and c["evidence"]["independent_review:accepted"] == 1
    assert "not evidence of broken promises" in outcomes(client, w)["caveat"]


def test_public_outcomes_hide_pending_feedback_identity_and_notes(w, client):
    make_participation(w.db, w.student, w.ev)
    fb = make_feedback(w.db, w.student, w.claim, "not_delivered", "published")
    fb.comment, fb.moderation_note = "Prize never arrived.", "internal: reporter is student@test.example"
    w.db.commit()
    raw = client.get(f"/api/events/{w.ev.id}/outcomes").text
    assert "Prize never arrived." in raw
    assert "internal:" not in raw and w.student.email not in raw and str(w.student.id) not in raw


def test_feedback_moderation_restricted_to_reviewers(w, client):
    make_participation(w.db, w.student, w.ev)
    fb = make_feedback(w.db, w.student, w.claim, "delivered", "pending")
    for user, code in ((None, 401), (w.student, 403), (w.organizer, 403)):
        r = client.post(f"/api/admin/feedback/{fb.id}/moderate", json={"status": "published"}, headers=auth(user) if user else {})
        assert r.status_code == code
    assert client.post(f"/api/admin/feedback/{fb.id}/moderate", json={"status": "published", "note": "ok"}, headers=auth(w.reviewer)).status_code == 200
    a = w.db.scalars(select(AuditLog).where(AuditLog.action == "feedback.moderated")).one()
    assert a.actor_id == w.reviewer.id and a.details["status"] == "published"
