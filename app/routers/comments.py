from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, status, HTTPException, Response, Query
from sqlalchemy.orm import Session

from .. import schema, model, oauth2
from ..database import get_db
from ..audit import log_activity
from ..rbac import Role, has_sufficient_role
from .tasks import verify_project_access

router = APIRouter(
    prefix="/comments",
    tags=["Comments"]
)


def verify_task_access(
    task_id: int, 
    user_id: int, 
    db: Session,
    min_role: Role = Role.VIEWER
) -> model.Tasks:
    """Helper to verify that a task exists, is active, and the user has the required role on its project."""
    task = db.query(model.Tasks).filter(
        model.Tasks.id == task_id,
        model.Tasks.is_deleted == False
    ).first()

    if not task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Task with id {task_id} not found"
        )

    # Verify user has required role access to the parent project and workspace
    verify_project_access(project_id=task.project_id, user_id=user_id, db=db, min_role=min_role)

    return task


@router.post("/task/{task_id}", status_code=status.HTTP_201_CREATED, response_model=schema.CommentsOut)
def create_comment(
    task_id: int,
    comment_data: schema.CommentsCreate,
    current_user: Annotated[model.Users, Depends(oauth2.get_current_active_user)],
    db: Session = Depends(get_db)
):
    """Requires at least MEMBER role to post comments."""
    task = verify_task_access(task_id=task_id, user_id=current_user.id, db=db, min_role=Role.MEMBER)

    new_comment = model.Comments(
        task_id=task_id,
        user_id=current_user.id,
        content=comment_data.content
    )

    db.add(new_comment)
    db.flush()

    # Get parent project for workspace ID and stage audit log atomically
    project = db.query(model.Project).filter(model.Project.id == task.project_id).first()
    if project:
        log_activity(
            db=db,
            workspace_id=project.workspace_id,
            user_id=current_user.id,
            action="COMMENT_CREATED",
            entity_type="comment",
            entity_id=new_comment.id,
            details=f"Posted comment on task '{task.title}'"
        )
    db.commit()
    db.refresh(new_comment)

    return new_comment


@router.get("/task/{task_id}", response_model=list[schema.CommentsOut])
def get_task_comments(
    task_id: int,
    current_user: Annotated[model.Users, Depends(oauth2.get_current_active_user)],
    db: Session = Depends(get_db),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0)
):
    """Requires at least VIEWER role to view comments."""
    verify_task_access(task_id=task_id, user_id=current_user.id, db=db, min_role=Role.VIEWER)

    comments = db.query(model.Comments).filter(
        model.Comments.task_id == task_id,
        model.Comments.is_deleted == False
    ).order_by(model.Comments.created_at.asc(), model.Comments.id.asc()).limit(limit).offset(offset).all()

    return comments


@router.put("/{id}", response_model=schema.CommentsOut)
def update_comment(
    id: int,
    comment_data: schema.CommentsCreate,
    current_user: Annotated[model.Users, Depends(oauth2.get_current_active_user)],
    db: Session = Depends(get_db)
):
    """Requires at least MEMBER role; only author can edit."""
    comment_query = db.query(model.Comments).filter(
        model.Comments.id == id,
        model.Comments.is_deleted == False
    )
    comment = comment_query.first()

    if not comment:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Comment with id {id} not found"
        )

    # Verify task access
    verify_task_access(task_id=comment.task_id, user_id=current_user.id, db=db, min_role=Role.MEMBER)

    # Only the author can edit their comment
    if comment.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You are not allowed to edit this comment"
        )

    comment_query.update(comment_data.model_dump(), synchronize_session=False)
    db.commit()
    db.refresh(comment)

    return comment


@router.delete("/{id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_comment(
    id: int,
    current_user: Annotated[model.Users, Depends(oauth2.get_current_active_user)],
    db: Session = Depends(get_db)
):
    """Soft deletes a comment (allowed for author or workspace/project admin)."""
    comment = db.query(model.Comments).filter(
        model.Comments.id == id,
        model.Comments.is_deleted == False
    ).first()

    if not comment:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Comment with id {id} not found"
        )

    # Verify task access
    task = verify_task_access(task_id=comment.task_id, user_id=current_user.id, db=db, min_role=Role.VIEWER)

    # Allowed if author, project owner, or workspace admin/owner
    project = db.query(model.Project).filter(model.Project.id == task.project_id).first()
    is_project_owner = project and project.owner_id == current_user.id

    is_ws_owner = False
    is_ws_admin = False
    if project:
        workspace = db.query(model.Workspace).filter(model.Workspace.id == project.workspace_id).first()
        is_ws_owner = workspace and workspace.owner_id == current_user.id
        ws_member = db.query(model.WorkspaceMember).filter(
            model.WorkspaceMember.workspace_id == project.workspace_id,
            model.WorkspaceMember.user_id == current_user.id
        ).first()
        is_ws_admin = ws_member and has_sufficient_role(ws_member.role, Role.ADMIN)

    if comment.user_id != current_user.id and not is_project_owner and not is_ws_owner and not is_ws_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You are not allowed to delete this comment"
        )

    # Soft delete
    comment.is_deleted = True
    comment.deleted_at = datetime.now(timezone.utc)

    # Log Audit Activity atomically
    if project:
        log_activity(
            db=db,
            workspace_id=project.workspace_id,
            user_id=current_user.id,
            action="COMMENT_DELETED",
            entity_type="comment",
            entity_id=id,
            details=f"Soft deleted comment on task '{task.title}'"
        )
    db.commit()

    return Response(status_code=status.HTTP_204_NO_CONTENT)
