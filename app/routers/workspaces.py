from typing import Annotated
from datetime import datetime, timezone

from fastapi import Depends, status, HTTPException, APIRouter, Response, Query
from sqlalchemy.orm import Session

from sqlalchemy import or_
from .. import model, schema, oauth2

from ..database import get_db
from ..rbac import Role, RequireWorkspaceRole

from ..audit import log_activity

router = APIRouter(
    prefix="/workspace",
    tags=["Workspace"]
)


@router.post("/", status_code=status.HTTP_201_CREATED, response_model=schema.WorkspaceOut)
def create_workspace(
    workspace: schema.WorkspaceCreate,
    current_user: Annotated[model.Users, Depends(oauth2.get_current_active_user)],
    db: Session = Depends(get_db)
):
    new_workspace = model.Workspace(
        name=workspace.name,
        owner_id=current_user.id
    )
    db.add(new_workspace)
    db.flush()

    # Automatically add the creator as an 'Owner' member
    member = model.WorkspaceMember(
        user_id=current_user.id,
        workspace_id=new_workspace.id,
        role=Role.OWNER.value
    )
    db.add(member)

    # Log Audit Activity
    log_activity(
        db=db,
        workspace_id=new_workspace.id,
        user_id=current_user.id,
        action="WORKSPACE_CREATED",
        entity_type="workspace",
        entity_id=new_workspace.id,
        details=f"Created workspace '{new_workspace.name}'"
    )
    db.commit()
    db.refresh(new_workspace)

    return new_workspace


@router.get("/", response_model=list[schema.WorkspaceOut])
def get_my_workspaces(
    current_user: Annotated[model.Users, Depends(oauth2.get_current_active_user)],
    db: Session = Depends(get_db),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0)
):
    """Retrieves all active (non-deleted) workspaces the current user owns or is a member of."""
    member_workspace_ids = [
        row[0] for row in db.query(model.WorkspaceMember.workspace_id).filter(
            model.WorkspaceMember.user_id == current_user.id
        ).all()
    ]

    workspaces = db.query(model.Workspace).filter(
        model.Workspace.is_deleted == False,
        or_(
            model.Workspace.owner_id == current_user.id,
            model.Workspace.id.in_(member_workspace_ids)
        )
    ).order_by(model.Workspace.created_at.desc(), model.Workspace.id.desc()).limit(limit).offset(offset).all()

    return workspaces


@router.get("/{workspace_id}", response_model=schema.WorkspaceOut)
def get_workspace(
    workspace_id: int,
    membership: Annotated[model.WorkspaceMember, Depends(RequireWorkspaceRole(Role.VIEWER))],
    db: Session = Depends(get_db)
):
    """Requires at least VIEWER role in the workspace."""
    workspace = db.query(model.Workspace).filter(
        model.Workspace.id == workspace_id,
        model.Workspace.is_deleted == False
    ).first()

    if not workspace:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Workspace with id {workspace_id} not found"
        )
    return workspace


@router.put("/{workspace_id}", response_model=schema.WorkspaceOut)
def update_workspace(
    workspace_id: int,
    workspace_data: schema.WorkspaceCreate,
    current_user: Annotated[model.Users, Depends(oauth2.get_current_active_user)],
    membership: Annotated[model.WorkspaceMember, Depends(RequireWorkspaceRole(Role.ADMIN))],
    db: Session = Depends(get_db)
):
    """Requires at least ADMIN or OWNER role in the workspace."""
    workspace_query = db.query(model.Workspace).filter(
        model.Workspace.id == workspace_id,
        model.Workspace.is_deleted == False
    )
    workspace = workspace_query.first()

    if not workspace:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Workspace with id {workspace_id} not found"
        )

    old_name = workspace.name
    workspace_query.update(workspace_data.model_dump(), synchronize_session=False)

    # Log Audit Activity
    log_activity(
        db=db,
        workspace_id=workspace_id,
        user_id=current_user.id,
        action="WORKSPACE_UPDATED",
        entity_type="workspace",
        entity_id=workspace_id,
        details=f"Renamed workspace from '{old_name}' to '{workspace_data.name}'"
    )
    db.commit()
    db.refresh(workspace)

    return workspace


@router.delete("/{workspace_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_workspace(
    workspace_id: int,
    current_user: Annotated[model.Users, Depends(oauth2.get_current_active_user)],
    membership: Annotated[model.WorkspaceMember, Depends(RequireWorkspaceRole(Role.OWNER))],
    db: Session = Depends(get_db)
):
    """Soft deletes the workspace (Requires OWNER role)."""
    workspace = db.query(model.Workspace).filter(
        model.Workspace.id == workspace_id,
        model.Workspace.is_deleted == False
    ).first()

    if not workspace:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Workspace with id {workspace_id} not found"
        )

    workspace.is_deleted = True
    workspace.deleted_at = datetime.now(timezone.utc)

    # Log Audit Activity
    log_activity(
        db=db,
        workspace_id=workspace_id,
        user_id=current_user.id,
        action="WORKSPACE_DELETED",
        entity_type="workspace",
        entity_id=workspace_id,
        details=f"Soft deleted workspace '{workspace.name}'"
    )
    db.commit()

    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/{workspace_id}/audit-logs", response_model=list[schema.AuditLogOut])
def get_workspace_audit_logs(
    workspace_id: int,
    membership: Annotated[model.WorkspaceMember, Depends(RequireWorkspaceRole(Role.ADMIN))],
    db: Session = Depends(get_db),
    limit: int = Query(default=50, le=100),
    offset: int = Query(default=0, ge=0)
):
    """Retrieves chronological activity logs for the workspace (Requires ADMIN or OWNER role)."""
    logs = db.query(model.AuditLog).filter(
        model.AuditLog.workspace_id == workspace_id
    ).order_by(model.AuditLog.created_at.desc()).limit(limit).offset(offset).all()

    return logs
