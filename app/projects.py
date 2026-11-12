"""Which projects a person may work in, and which one they are looking at.

Rule: admins reach every project; everyone else needs a membership row. Nothing is open by
default, so a project with no members is visible to admins only.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from .enums import Role
from .models import Project, ProjectMember, User


def accessible_projects(session: Session, user: User) -> list[Project]:
    q = select(Project).order_by(Project.id)
    if user.role != Role.admin:
        q = q.join(ProjectMember, ProjectMember.project_id == Project.id).where(
            ProjectMember.user_id == user.id)
    return list(session.scalars(q))


def can_access_project(session: Session, user: User, project_id: int) -> bool:
    if user.role == Role.admin:
        return session.get(Project, project_id) is not None
    return session.scalar(select(ProjectMember.id).where(
        ProjectMember.user_id == user.id, ProjectMember.project_id == project_id)) is not None


def resolve_project(session: Session, user: User, wanted_id: int | None) -> Project | None:
    """The project the person chose, if they may still use it; otherwise their first one."""
    projects = accessible_projects(session, user)
    for p in projects:
        if p.id == wanted_id:
            return p
    return projects[0] if projects else None


# Roles a project may give. Admin is deliberately not one of them: it is an instance-wide
# role (loading sources, creating projects, managing people) and is never granted per project.
PROJECT_ROLES = (Role.approver, Role.viewer, Role.restricted)


def effective_role(session: Session, user: User, wanted_id: int | None) -> Role:
    """The role this person has in the project they are looking at.

    Admins keep admin everywhere. Otherwise a role set on their membership wins, and a person
    with none set keeps their default role.
    """
    if user.role == Role.admin:
        return Role.admin
    project = resolve_project(session, user, wanted_id)
    if project is None:
        return user.role
    row = session.scalar(select(ProjectMember).where(
        ProjectMember.project_id == project.id, ProjectMember.user_id == user.id))
    return row.role if row is not None and row.role is not None else user.role


def set_member_role(session: Session, project: Project, user: User, role: Role | None) -> bool:
    """Set (or clear, with None) a member's role in one project. False if they are not a member."""
    if role is not None and role not in PROJECT_ROLES:
        raise ValueError("Admin is not a project role.")
    row = session.scalar(select(ProjectMember).where(
        ProjectMember.project_id == project.id, ProjectMember.user_id == user.id))
    if row is None:
        return False
    row.role = role
    return True


def add_member(session: Session, project: Project, user: User, by: str,
               role: Role | None = None) -> bool:
    if session.scalar(select(ProjectMember.id).where(
            ProjectMember.project_id == project.id, ProjectMember.user_id == user.id)):
        return False
    if role is not None and role not in PROJECT_ROLES:
        raise ValueError("Admin is not a project role.")
    session.add(ProjectMember(project_id=project.id, user_id=user.id, added_by=by, role=role))
    return True


def remove_member(session: Session, project: Project, user: User) -> bool:
    row = session.scalar(select(ProjectMember).where(
        ProjectMember.project_id == project.id, ProjectMember.user_id == user.id))
    if row is None:
        return False
    session.delete(row)
    return True
