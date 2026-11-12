"""Pages for projects, the audit log, the decision timeline and the bus-factor view."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .audit_log import KINDS, audit_entries
from .db import get_session
from .enums import REVIEWER_ROLES, ClaimType
from .handover import can_view, get_handover, is_stale
from .handover_web import require_admin, require_user
from .models import Project, ProjectMember, User
from .projects import accessible_projects, add_member, can_access_project, remove_member
from .timeline import TIMELINE_TYPES, build_bus_factor, build_timeline
from .web import check_csrf, project_for, render, require_reviewer

router = APIRouter()


def _flash(request: Request, msg: str, to: str):
    request.session["flash"] = msg
    return RedirectResponse(to, status_code=303)


# ------------------------------------------------------------------ guide


@router.get("/guide")
def guide_page(request: Request, user: User = Depends(require_user),
               session: Session = Depends(get_session)):
    project = project_for(session, request, user)
    return render(request, "guide.html", user, project=project,
                  reviewer=user.role in REVIEWER_ROLES)


# ------------------------------------------------------------------ projects


@router.get("/projects")
def projects_page(request: Request, user: User = Depends(require_user),
                  session: Session = Depends(get_session)):
    projects = accessible_projects(session, user)
    current = None
    if projects:
        current = project_for(session, request, user)
    members: dict[int, list[User]] = {}
    others: dict[int, list[User]] = {}
    if user.role.value == "admin":
        everyone = list(session.scalars(select(User).order_by(User.display_name)))
        for p in projects:
            ids = {m.user_id for m in session.scalars(
                select(ProjectMember).where(ProjectMember.project_id == p.id))}
            members[p.id] = [u for u in everyone if u.id in ids]
            others[p.id] = [u for u in everyone if u.id not in ids]
    return render(request, "projects.html", user, projects=projects, current=current,
                  members=members, others=others)


@router.post("/projects/switch")
def switch_project(request: Request, project_id: int = Form(0), csrf: str = Form(""),
                   user: User = Depends(require_user), session: Session = Depends(get_session)):
    check_csrf(request, csrf)
    if not can_access_project(session, user, project_id):
        raise HTTPException(status_code=404, detail="Project not found.")
    request.session["project_id"] = project_id
    return _flash(request, "Switched project.", "/handover" if user.role not in REVIEWER_ROLES else "/review")


@router.post("/projects/new")
def new_project(request: Request, name: str = Form(""), outgoing: str = Form(""),
                description: str = Form(""), csrf: str = Form(""),
                user: User = Depends(require_admin), session: Session = Depends(get_session)):
    check_csrf(request, csrf)
    name = " ".join(name.split())[:200]
    if not name:
        return _flash(request, "Give the project a name.", "/projects")
    if session.scalar(select(Project.id).where(func.lower(Project.name) == name.lower())):
        return _flash(request, "A project with that name already exists.", "/projects")
    project = Project(name=name, description=description.strip()[:1000],
                      outgoing_member=" ".join(outgoing.split())[:128] or None)
    session.add(project)
    session.flush()
    add_member(session, project, user, user.username)
    session.commit()
    request.session["project_id"] = project.id
    return _flash(request, f"Created {name}. Add people to it below, then load sources.", "/projects")


@router.post("/projects/{project_id}/members/{action}")
def change_members(project_id: int, action: str, request: Request, user_id: int = Form(0),
                   csrf: str = Form(""), admin: User = Depends(require_admin),
                   session: Session = Depends(get_session)):
    check_csrf(request, csrf)
    project, person = session.get(Project, project_id), session.get(User, user_id)
    if project is None or person is None:
        raise HTTPException(status_code=404, detail="Not found.")
    if action == "add":
        changed = add_member(session, project, person, admin.username)
        msg = f"Added {person.display_name}." if changed else "Already a member."
    elif action == "remove":
        changed = remove_member(session, project, person)
        msg = f"Removed {person.display_name}." if changed else "Not a member."
    else:
        raise HTTPException(status_code=404, detail="Unknown action.")
    session.commit()
    return _flash(request, msg, "/projects")


# ------------------------------------------------------------------ audit log


@router.get("/audit")
def audit_page(request: Request, kind: str = "", user: User = Depends(require_reviewer),
               session: Session = Depends(get_session)):
    project = project_for(session, request, user)
    kind = kind if kind in KINDS else ""
    entries = audit_entries(session, project, user.role, kind)
    return render(request, "audit.html", user, project=project, entries=entries, kind=kind, kinds=KINDS)


# ------------------------------------------------------------------ timeline


@router.get("/timeline")
def timeline_page(request: Request, type: str = "", drafts: str = "",
                  user: User = Depends(require_user), session: Session = Depends(get_session)):
    project = project_for(session, request, user)
    reviewer = user.role in REVIEWER_ROLES
    if not reviewer:
        # Same gate as the handover: nothing until a current sign-off exists.
        handover = get_handover(session, project)
        if not can_view(user, handover) or is_stale(session, project, handover):
            return render(request, "handover_pending.html", user, project=project)
    types = TIMELINE_TYPES
    if type in {t.value for t in TIMELINE_TYPES}:
        types = (ClaimType(type),)
    else:
        type = ""
    items = build_timeline(session, project, user.role, include_drafts=bool(drafts) and reviewer,
                           types=types)
    return render(request, "timeline.html", user, project=project, items=items, type=type,
                  types=[t.value for t in TIMELINE_TYPES], drafts=bool(drafts) and reviewer,
                  reviewer=reviewer)


# ------------------------------------------------------------------ bus factor


@router.get("/bus-factor")
def bus_factor_page(request: Request, user: User = Depends(require_reviewer),
                    session: Session = Depends(get_session)):
    project = project_for(session, request, user)
    return render(request, "bus_factor.html", user, project=project,
                  result=build_bus_factor(session, project, user.role))
