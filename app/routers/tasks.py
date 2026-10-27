from typing import Annotated, Optional
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, status, HTTPException, Response, Query
from sqlalchemy.orm import Session

from .. import schema, model, oauth2
from ..database import get_db
from ..audit import log_activity
from ..rbac import Role, has_sufficient_role

router = APIRouter(
    prefix="/tasks",
    tags=["Tasks"]
)


def verify_project_access(
    project_id: int,
    user_id: int, 
    db: Session,
    min_role: Role = Role.VIEWER
) -> model.Project:
    """Verifies that the project exists, user has access, and meets the minimum required role rank."""
    project = db.query(model.Project).filter(
        model.Project.id == project_id,
        model.Project.is_deleted == False
    ).first()

    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Project with id {project_id} not found"
        )

    # Check workspace existence
    workspace = db.query(model.Workspace).filter(
        model.Workspace.id == project.workspace_id,
        model.Workspace.is_deleted == False
    ).first()

    if not workspace:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Parent workspace not found"
        )

    # Determine user role in workspace
    if workspace.owner_id == user_id:
        user_role = Role.OWNER
    else:
        ws_member = db.query(model.WorkspaceMember).filter(
            model.WorkspaceMember.workspace_id == project.workspace_id,
            model.WorkspaceMember.user_id == user_id
        ).first()

        if not ws_member:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You are not a member of the workspace this project belongs to"
            )
        user_role = ws_member.role

    # If project is private, check if user is the project owner or a project member
    if project.private:
        proj_member = db.query(model.ProjectMember).filter(
            model.ProjectMember.project_id == project.id,
            model.ProjectMember.user_id == user_id
        ).first()

        if project.owner_id != user_id and not proj_member and workspace.owner_id != user_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have access to this private project"
            )

    # Enforce RBAC Role Hierarchy
    if not has_sufficient_role(user_role, min_role):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Insufficient permissions. Minimum role required: {min_role.value.capitalize()}."
        )

    return project


def verify_task_assignee(assignee_id: int, project: model.Project, db: Session):
    assignee = db.query(model.Users).filter(model.Users.id == assignee_id).first()
    if not assignee:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Assignee with user id {assignee_id} does not exist"
        )
    # Check if assignee belongs to the workspace
    ws_membership = db.query(model.WorkspaceMember).filter(
        model.WorkspaceMember.workspace_id == project.workspace_id,
        model.WorkspaceMember.user_id == assignee_id
    ).first()
    workspace = db.query(model.Workspace).filter(model.Workspace.id == project.workspace_id).first()
    is_ws_owner = workspace and workspace.owner_id == assignee_id

    if not ws_membership and not is_ws_owner:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Assignee must be a member of this workspace"
        )

    # If project is private, check if assignee has access to the project
    if project.private:
        proj_member = db.query(model.ProjectMember).filter(
            model.ProjectMember.project_id == project.id,
            model.ProjectMember.user_id == assignee_id
        ).first()
        if not proj_member and project.owner_id != assignee_id and not is_ws_owner:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Assignee does not have access to this private project"
            )


@router.post("/project/{project_id}", status_code=status.HTTP_201_CREATED, response_model=schema.TasksOut)
def create_task(
    project_id: int,
    task: schema.TasksCreate,
    current_user: Annotated[model.Users, Depends(oauth2.get_current_active_user)],
    db: Session = Depends(get_db)
):
    """Requires at least MEMBER role to create a task."""
    project = verify_project_access(project_id=project_id, user_id=current_user.id, db=db, min_role=Role.MEMBER)

    # Verify assignee workspace/project access
    if task.assignee_id is not None:
        verify_task_assignee(assignee_id=task.assignee_id, project=project, db=db)

    new_task = model.Tasks(
        project_id=project_id,
        title=task.title,
        description=task.description,
        status=task.status.value if hasattr(task.status, "value") else (task.status or "pending"),
        priority=task.priority.value if hasattr(task.priority, "value") else (task.priority or "medium"),
        assignee_id=task.assignee_id,
        due_date=task.due_date
    )

    db.add(new_task)
    db.flush()

    # Log Audit Activity atomically
    log_activity(
        db=db,
        workspace_id=project.workspace_id,
        user_id=current_user.id,
        action="TASK_CREATED",
        entity_type="task",
        entity_id=new_task.id,
        details=f"Created task '{new_task.title}' with priority '{new_task.priority}'"
    )
    db.commit()
    db.refresh(new_task)

    return new_task


@router.get("/project/{project_id}", response_model=list[schema.TasksOut])
def get_project_tasks(
    project_id: int,
    current_user: Annotated[model.Users, Depends(oauth2.get_current_active_user)],
    db: Session = Depends(get_db),
    status_filter: Optional[schema.TaskStatus] = Query(default=None, alias="status"),
    priority_filter: Optional[schema.TaskPriority] = Query(default=None, alias="priority"),
    assignee_id: Optional[int] = None,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0)
):
    """Requires at least VIEWER role to view project tasks."""
    verify_project_access(project_id=project_id, user_id=current_user.id, db=db, min_role=Role.VIEWER)

    query = db.query(model.Tasks).filter(
        model.Tasks.project_id == project_id,
        model.Tasks.is_deleted == False
    )

    if status_filter:
        query = query.filter(model.Tasks.status == status_filter.value)
    if priority_filter:
        query = query.filter(model.Tasks.priority == priority_filter.value)
    if assignee_id is not None:
        query = query.filter(model.Tasks.assignee_id == assignee_id)

    tasks = query.order_by(model.Tasks.created_at.desc(), model.Tasks.id.desc()).limit(limit).offset(offset).all()
    return tasks


@router.get("/{id}", response_model=schema.TasksOut)
def get_task(
    id: int,
    current_user: Annotated[model.Users, Depends(oauth2.get_current_active_user)],
    db: Session = Depends(get_db)
):
    """Requires at least VIEWER role to view task details."""
    task = db.query(model.Tasks).filter(
        model.Tasks.id == id,
        model.Tasks.is_deleted == False
    ).first()

    if not task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Task with id {id} not found"
        )

    verify_project_access(project_id=task.project_id, user_id=current_user.id, db=db, min_role=Role.VIEWER)

    return task


@router.put("/{id}", response_model=schema.TasksOut)
def update_task(
    id: int,
    task_data: schema.TasksUpdate,
    current_user: Annotated[model.Users, Depends(oauth2.get_current_active_user)],
    db: Session = Depends(get_db)
):
    """Requires at least MEMBER role to update a task."""
    task_query = db.query(model.Tasks).filter(
        model.Tasks.id == id,
        model.Tasks.is_deleted == False
    )
    task = task_query.first()

    if not task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Task with id {id} not found"
        )

    project = verify_project_access(project_id=task.project_id, user_id=current_user.id, db=db, min_role=Role.MEMBER)

    update_data = task_data.model_dump(exclude_unset=True)

    if "assignee_id" in update_data and update_data["assignee_id"] is not None:
        verify_task_assignee(assignee_id=update_data["assignee_id"], project=project, db=db)

    if "status" in update_data and hasattr(update_data["status"], "value"):
        update_data["status"] = update_data["status"].value
    if "priority" in update_data and hasattr(update_data["priority"], "value"):
        update_data["priority"] = update_data["priority"].value

    if update_data:
        task_query.update(update_data, synchronize_session=False)

        # Log Audit Activity atomically
        log_activity(
            db=db,
            workspace_id=project.workspace_id,
            user_id=current_user.id,
            action="TASK_UPDATED",
            entity_type="task",
            entity_id=task.id,
            details=f"Updated task '{task.title}' fields: {list(update_data.keys())}"
        )
        db.commit()
        db.refresh(task)

    return task


@router.delete("/{id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_task(
    id: int,
    current_user: Annotated[model.Users, Depends(oauth2.get_current_active_user)],
    db: Session = Depends(get_db)
):
    """Requires at least ADMIN role or project creator to soft delete a task."""
    task = db.query(model.Tasks).filter(
        model.Tasks.id == id,
        model.Tasks.is_deleted == False
    ).first()

    if not task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Task with id {id} not found"
        )

    project = verify_project_access(project_id=task.project_id, user_id=current_user.id, db=db, min_role=Role.ADMIN)

    task_title = task.title

    # Soft delete
    task.is_deleted = True
    task.deleted_at = datetime.now(timezone.utc)

    # Log Audit Activity atomically
    log_activity(
        db=db,
        workspace_id=project.workspace_id,
        user_id=current_user.id,
        action="TASK_DELETED",
        entity_type="task",
        entity_id=id,
        details=f"Soft deleted task '{task_title}'"
    )
    db.commit()

    return Response(status_code=status.HTTP_204_NO_CONTENT)
