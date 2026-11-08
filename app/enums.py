"""Shared vocabularies for claims, sources, roles and sensitivity.

Sensitivity is an ordered scale. A role has a clearance (the highest sensitivity it may
see). Anything above a role's clearance is never shown to that role.
"""

from enum import Enum


class ClaimType(str, Enum):
    decision = "decision"
    risk = "risk"
    dependency = "dependency"
    owner = "owner"
    open_question = "open_question"
    next_action = "next_action"
    blocker = "blocker"
    recurring_problem = "recurring_problem"
    contact = "contact"


class Confidence(str, Enum):
    verified = "verified"          # cited snippet exists in the source and supports the claim
    inferred = "inferred"          # plausible reading of the evidence, not stated outright
    conflicting = "conflicting"    # sources disagree
    unsupported = "unsupported"    # no usable evidence; shown as a gap, never as fact


class Sensitivity(str, Enum):
    public = "public"
    team = "team"
    restricted = "restricted"
    confidential = "confidential"


class ReviewStatus(str, Enum):
    generated = "generated"
    edited = "edited"
    approved = "approved"
    rejected = "rejected"


class Role(str, Enum):
    admin = "admin"            # connects sources, manages the project
    approver = "approver"      # reviews and approves the handover
    viewer = "viewer"          # the incoming person
    restricted = "restricted"  # e.g. a mentor: partial context only


class SourceKind(str, Enum):
    notes = "notes"
    chat = "chat"
    tasks = "tasks"
    github = "github"


class Stance(str, Enum):
    supports = "supports"
    contradicts = "contradicts"


class ChangeType(str, Enum):
    generated = "generated"
    edit = "edit"
    approve = "approve"
    reject = "reject"


class HandoverStatus(str, Enum):
    draft = "draft"
    approved = "approved"
    shared = "shared"


SENSITIVITY_RANK = {
    Sensitivity.public: 0,
    Sensitivity.team: 1,
    Sensitivity.restricted: 2,
    Sensitivity.confidential: 3,
}

ROLE_CLEARANCE = {
    Role.admin: Sensitivity.confidential,
    Role.approver: Sensitivity.confidential,
    Role.viewer: Sensitivity.restricted,
    Role.restricted: Sensitivity.team,
}
