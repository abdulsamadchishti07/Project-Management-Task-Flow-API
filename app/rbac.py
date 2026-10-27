from fastapi import Depends, HTTPException, status
from sqlalchemy.orm import Session

from . import model, oauth2
from .database import get_db

from typing import Annotated
from enum import Enum

class Role(str, Enum):
    VIEWER = "viewer"
    MEMBER = "member"
    ADMIN = "admin"
    OWNER = "owner"


# Numerical rank for role hierarchy: Higher number means higher authority
ROLE_HIERARCHY: dict[Role, int] = {
    Role.VIEWER: 1,
    Role.MEMBER: 2,
    Role.ADMIN: 3,
    Role.OWNER: 4,
}


def has_sufficient_role(user_role: str | Role, required_role: str | Role) -> bool:
    """
    Compares the user's role against the required role.
    Returns True if the user's role rank is equal to or higher than the required role rank.

    Examples:
        has_sufficient_role("admin", "member") -> True  (Rank 3 >= Rank 2)
        has_sufficient_role("viewer", "member") -> False (Rank 1 < Rank 2)
        has_sufficient_role("owner", "admin")  -> True  (Rank 4 >= Rank 3)
    """
    try:
        u_val = user_role.value if isinstance(user_role, Role) else str(user_role).lower()
        r_val = required_role.value if isinstance(required_role, Role) else str(required_role).lower()
        user_r = Role(u_val)
        req_r = Role(r_val)
    except (ValueError, AttributeError):
        return False

    return ROLE_HIERARCHY.get(user_r, 0) >= ROLE_HIERARCHY.get(req_r, 0)


class RequireWorkspaceRole:
    """
    FastAPI Dependency Factory that enforces minimum role permissions in a workspace.

    Usage:
        @router.post("/workspace/{workspace_id}/projects")
        def create_project(
            workspace_id: int,
            membership = Depends(RequireWorkspaceRole(Role.MEMBER))
        ):
            ...
    """

    def __init__(self, required_role: Role):
        self.required_role = required_role

    def __call__(
        self,
        workspace_id: int,
        current_user: Annotated[model.Users, Depends(oauth2.get_current_active_user)],
        db: Annotated[Session, Depends(get_db)],
    ) -> model.WorkspaceMember:
        workspace = db.query(model.Workspace).filter(
            model.Workspace.id == workspace_id,
            model.Workspace.is_deleted == False
        ).first()
        if not workspace:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Workspace with id {workspace_id} not found"
            )

        member = db.query(model.WorkspaceMember).filter(
            model.WorkspaceMember.workspace_id == workspace_id,
            model.WorkspaceMember.user_id == current_user.id
        ).first()

        # If user is the creator/owner of the workspace, grant OWNER authority
        if workspace.owner_id == current_user.id:
            user_role = Role.OWNER
            if not member:
                member = model.WorkspaceMember(
                    user_id=current_user.id,
                    workspace_id=workspace_id,
                    role=Role.OWNER.value
                )
        elif member:
            user_role = member.role
        else:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You are not a member of this workspace"
            )

        if not has_sufficient_role(user_role, self.required_role):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Insufficient permissions. Required role: {self.required_role.value.capitalize()} or higher."
            )

        return member
