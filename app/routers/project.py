from typing import Annotated
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, status, HTTPException, Response, Query
from sqlalchemy.orm import Session

from sqlalchemy import or_
from .. import schema, model, oauth2

from ..database import get_db
from ..rbac import Role, RequireWorkspaceRole, has_sufficient_role

from ..redis_client import get_cached_json, set_cached_json, delete_cache_pattern
from ..audit import log_activity

router = APIRouter(
    prefix="/project",
    tags=["Projects"]
)


@router.post("/workspace/{workspace_id}", status_code=status.HTTP_201_CREATED, response_model=schema.ProjectOut)
def create_project(
    workspace_id: int,
    project: schema.ProjectCreate,
    current_user: Annotated[model.Users, Depends(oauth2.get_current_active_user)],
    membership: Annotated[model.WorkspaceMember, Depends(RequireWorkspaceRole(Role.MEMBER))],
    db: Session = Depends(get_db)
):
    """Requires at least MEMBER role in the workspace to create a project."""
    new_project = model.Project(
        name=project.name,
        description=project.description,
        private=project.private if project.private is not None else False,
        workspace_id=workspace_id,
        owner_id=current_user.id
    )

    db.add(new_project)
    db.flush()

    # Automatically add the creator as an 'Admin' in the project
    member = model.ProjectMember(
        user_id=current_user.id,
        project_id=new_project.id,
        role=Role.ADMIN.value
    )
    db.add(member)

    # Invalidate workspace projects cache
    delete_cache_pattern(f"projects:ws:{workspace_id}:*")

    # Log Audit Activity atomically
    log_activity(
        db=db,
        workspace_id=workspace_id,
        user_id=current_user.id,
        action="PROJECT_CREATED",
        entity_type="project",
        entity_id=new_project.id,
        details=f"Created project '{new_project.name}' (private={new_project.private})"
    )
    db.commit()
    db.refresh(new_project)

    return new_project


@router.get("/workspace/{workspace_id}", response_model=list[schema.ProjectOut])
def get_workspace_projects(
    workspace_id: int,
    current_user: Annotated[model.Users, Depends(oauth2.get_current_active_user)],
    membership: Annotated[model.WorkspaceMember, Depends(RequireWorkspaceRole(Role.VIEWER))],
    db: Session = Depends(get_db),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0)
):
    """Requires at least VIEWER role in the workspace. Cached in Redis."""
    cache_key = f"projects:ws:{workspace_id}:user:{current_user.id}:lim:{limit}:off:{offset}"
    cached_data = get_cached_json(cache_key)
    if cached_data is not None:
        return cached_data

    # Fetch IDs of private projects where the current user is a member
    member_project_ids = [
        row[0] for row in db.query(model.ProjectMember.project_id).filter(
            model.ProjectMember.user_id == current_user.id
        ).all()
    ]

    # Return active (non-deleted) projects with deterministic ordering
    projects = db.query(model.Project).filter(
        model.Project.workspace_id == workspace_id,
        model.Project.is_deleted == False,
        or_(
            model.Project.private == False,
            model.Project.owner_id == current_user.id,
            model.Project.id.in_(member_project_ids)
        )
    ).order_by(model.Project.created_at.desc(), model.Project.id.desc()).limit(limit).offset(offset).all()

    # Serialize & store in Redis (3-minute TTL)
    serialized = [schema.ProjectOut.model_validate(p).model_dump() for p in projects]
    set_cached_json(cache_key, serialized, expire_seconds=180)

    return projects


@router.get("/{id}", response_model=schema.ProjectOut)
def get_project(
    id: int,
    current_user: Annotated[model.Users, Depends(oauth2.get_current_active_user)],
    db: Session = Depends(get_db)
):
    project = db.query(model.Project).filter(
        model.Project.id == id,
        model.Project.is_deleted == False
    ).first()

    if project is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Project with id {id} not found"
        )

    # Verify parent workspace is active
    workspace = db.query(model.Workspace).filter(
        model.Workspace.id == project.workspace_id,
        model.Workspace.is_deleted == False
    ).first()
    if not workspace:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Parent workspace not found"
        )

    # Verify user has at least VIEWER role in the parent workspace
    ws_membership = db.query(model.WorkspaceMember).filter(
        model.WorkspaceMember.workspace_id == project.workspace_id,
        model.WorkspaceMember.user_id == current_user.id
    ).first()
    is_ws_owner = workspace.owner_id == current_user.id

    if not ws_membership and not is_ws_owner:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You are not a member of this workspace"
        )

    # Privacy check for private projects
    if project.private:
        is_project_member = db.query(model.ProjectMember).filter(
            model.ProjectMember.project_id == project.id,
            model.ProjectMember.user_id == current_user.id
        ).first()

        if project.owner_id != current_user.id and not is_project_member and not is_ws_owner:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have access to this private project"
            )

    return project


@router.put("/{id}", response_model=schema.ProjectOut)
def update_project(
    id: int,
    project_data: schema.ProjectCreate,
    current_user: Annotated[model.Users, Depends(oauth2.get_current_active_user)],
    db: Session = Depends(get_db)
):
    project_query = db.query(model.Project).filter(
        model.Project.id == id,
        model.Project.is_deleted == False
    )
    project = project_query.first()

    if project is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Project with id {id} not found"
        )

    # Verify parent workspace is active
    workspace = db.query(model.Workspace).filter(
        model.Workspace.id == project.workspace_id,
        model.Workspace.is_deleted == False
    ).first()
    if not workspace:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Parent workspace not found"
        )

    is_ws_owner = workspace.owner_id == current_user.id
    ws_member = db.query(model.WorkspaceMember).filter(
        model.WorkspaceMember.workspace_id == project.workspace_id,
        model.WorkspaceMember.user_id == current_user.id
    ).first()
    is_ws_admin = ws_member and has_sufficient_role(ws_member.role, Role.ADMIN)

    # Check project-level admin / ownership
    proj_member = db.query(model.ProjectMember).filter(
        model.ProjectMember.project_id == project.id,
        model.ProjectMember.user_id == current_user.id
    ).first()
    is_project_admin = proj_member and proj_member.role == Role.ADMIN.value
    is_project_owner = project.owner_id == current_user.id

    if not is_project_owner and not is_project_admin and not is_ws_owner and not is_ws_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You are not allowed to update this project"
        )

    old_name = project.name
    update_dict = project_data.model_dump(exclude_unset=True)
    if update_dict:
        project_query.update(update_dict, synchronize_session=False)

        # Log Audit Activity atomically
        log_activity(
            db=db,
            workspace_id=project.workspace_id,
            user_id=current_user.id,
            action="PROJECT_UPDATED",
            entity_type="project",
            entity_id=project.id,
            details=f"Updated project '{old_name}'"
        )
        db.commit()
        db.refresh(project)

        # Invalidate cache for this workspace
        delete_cache_pattern(f"projects:ws:{project.workspace_id}:*")

    return project


@router.delete("/{id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_project(
    id: int,
    current_user: Annotated[model.Users, Depends(oauth2.get_current_active_user)],
    db: Session = Depends(get_db)
):
    project_query = db.query(model.Project).filter(
        model.Project.id == id,
        model.Project.is_deleted == False
    )
    project = project_query.first()

    if project is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Project with id {id} not found"
        )

    # Allow delete if user is project owner OR workspace admin/owner
    workspace = db.query(model.Workspace).filter(
        model.Workspace.id == project.workspace_id,
        model.Workspace.is_deleted == False
    ).first()
    is_ws_owner = workspace and workspace.owner_id == current_user.id

    ws_member = db.query(model.WorkspaceMember).filter(
        model.WorkspaceMember.workspace_id == project.workspace_id,
        model.WorkspaceMember.user_id == current_user.id
    ).first()
    is_ws_admin = ws_member and has_sufficient_role(ws_member.role, Role.ADMIN)

    if project.owner_id != current_user.id and not is_ws_owner and not is_ws_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You are not allowed to delete this project"
        )

    workspace_id = project.workspace_id
    project_title = project.name

    # Soft Delete
    project.is_deleted = True
    project.deleted_at = datetime.now(timezone.utc)

    # Log Audit Activity atomically
    log_activity(
        db=db,
        workspace_id=workspace_id,
        user_id=current_user.id,
        action="PROJECT_DELETED",
        entity_type="project",
        entity_id=id,
        details=f"Soft deleted project '{project_title}'"
    )
    db.commit()

    # Invalidate cache for this workspace
    delete_cache_pattern(f"projects:ws:{workspace_id}:*")

    return Response(status_code=status.HTTP_204_NO_CONTENT)
