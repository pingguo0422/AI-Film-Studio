"""Centralized project-role authorization policy."""
from __future__ import annotations
from enum import Enum
from uuid import UUID
from sqlalchemy import select
from sqlalchemy.orm import Session
from backend.app.models import MemberRole, ProjectMember


class AuthorizationError(PermissionError):
    pass


class ProjectPermission(str, Enum):
    read = "project:read"
    contribute = "project:contribute"
    manage_members = "project:manage_members"
    approve = "project:approve"
    administer = "project:administer"

ROLE_PERMISSIONS: dict[MemberRole, frozenset[ProjectPermission]] = {
    MemberRole.owner: frozenset(ProjectPermission),
    MemberRole.producer: frozenset({ProjectPermission.read, ProjectPermission.contribute, ProjectPermission.manage_members, ProjectPermission.approve}),
    MemberRole.director: frozenset({ProjectPermission.read, ProjectPermission.contribute, ProjectPermission.approve}),
    MemberRole.department_lead: frozenset({ProjectPermission.read, ProjectPermission.contribute}),
    MemberRole.collaborator: frozenset({ProjectPermission.read, ProjectPermission.contribute}),
    MemberRole.viewer: frozenset({ProjectPermission.read}),
}


def get_project_membership(db: Session, *, project_id: UUID, principal_id: UUID) -> ProjectMember:
    member = db.scalar(select(ProjectMember).where(
        ProjectMember.project_id == project_id,
        ProjectMember.principal_id == principal_id,
        ProjectMember.is_active.is_(True),
    ))
    if member is None:
        raise AuthorizationError("active project membership required")
    return member


def require_project_permission(
    db: Session, *, project_id: UUID, principal_id: UUID,
    permission: ProjectPermission,
) -> ProjectMember:
    member = get_project_membership(db, project_id=project_id, principal_id=principal_id)
    role = member.role if isinstance(member.role, MemberRole) else MemberRole(member.role)
    if permission not in ROLE_PERMISSIONS[role]:
        raise AuthorizationError(f"project role {role.value!r} lacks {permission.value}")
    return member
