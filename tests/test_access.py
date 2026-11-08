import pytest

from app.access import (
    effective_sensitivity,
    filter_handover,
    filter_review,
    role_can_see,
    visible_in_handover,
    visible_in_review,
)
from app.enums import ReviewStatus, Role, Sensitivity

from .conftest import make_claim

S = Sensitivity
R = Role

CLEARANCE_MATRIX = {
    R.admin:      {S.public: True, S.team: True,  S.restricted: True,  S.confidential: True},
    R.approver:   {S.public: True, S.team: True,  S.restricted: True,  S.confidential: True},
    R.viewer:     {S.public: True, S.team: True,  S.restricted: True,  S.confidential: False},
    R.restricted: {S.public: True, S.team: True,  S.restricted: False, S.confidential: False},
}


@pytest.mark.parametrize("role", list(Role))
@pytest.mark.parametrize("sens", list(Sensitivity))
def test_clearance_matrix(role, sens):
    assert role_can_see(role, sens) is CLEARANCE_MATRIX[role][sens]


@pytest.mark.parametrize("claim_s,chunk_s,source_s,expected", [
    (S.team, S.team, S.team, S.team),
    (S.team, S.confidential, S.team, S.confidential),   # a confidential message taints the claim
    (S.team, S.team, S.confidential, S.confidential),   # so does a confidential source
    (S.confidential, S.public, S.public, S.confidential),
    (S.public, S.restricted, S.team, S.restricted),
])
def test_effective_sensitivity_is_the_highest_label(session, project, claim_s, chunk_s,
                                                    source_s, expected):
    claim = make_claim(session, project, claim_sens=claim_s, chunk_sens=chunk_s,
                       source_sens=source_s)
    assert effective_sensitivity(claim) == expected


def test_only_approved_claims_reach_a_handover(session, project):
    claim = make_claim(session, project)
    for role in Role:
        assert not visible_in_handover(role, claim)   # generated: not truth yet
    claim.approve(by="Meera")
    for role in Role:
        assert visible_in_handover(role, claim)


def test_rejected_claims_never_appear_in_any_handover(session, project):
    claim = make_claim(session, project)
    claim.approve(by="Meera")
    claim.reject(by="Meera")
    assert claim.review_status == ReviewStatus.rejected
    for role in Role:
        assert not visible_in_handover(role, claim)
    assert filter_handover(Role.admin, [claim]) == []


def test_edited_claim_drops_out_of_handover_until_reapproved(session, project):
    claim = make_claim(session, project)
    claim.approve(by="Meera")
    claim.edit("new wording", by="Riya")
    assert not visible_in_handover(Role.viewer, claim)
    claim.approve(by="Meera")
    assert visible_in_handover(Role.viewer, claim)


def test_confidential_evidence_hides_an_approved_claim_from_lower_roles(session, project):
    claim = make_claim(session, project, chunk_sens=S.confidential)
    claim.approve(by="Meera")
    assert visible_in_handover(Role.approver, claim)
    assert not visible_in_handover(Role.viewer, claim)
    assert not visible_in_handover(Role.restricted, claim)


def test_review_queue_is_for_approvers_and_admins_only(session, project):
    claim = make_claim(session, project)             # still 'generated'
    assert visible_in_review(Role.approver, claim)
    assert visible_in_review(Role.admin, claim)
    assert not visible_in_review(Role.viewer, claim)
    assert not visible_in_review(Role.restricted, claim)
    assert filter_review(Role.viewer, [claim]) == []


def test_review_queue_still_respects_clearance_and_shows_rejected(session, project):
    claim = make_claim(session, project)
    claim.reject(by="Meera")
    assert visible_in_review(Role.approver, claim)   # reviewers can undo a rejection
