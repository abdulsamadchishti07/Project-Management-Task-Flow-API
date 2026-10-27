from typing import Annotated
from fastapi import APIRouter, Depends, status, HTTPException, Response, BackgroundTasks

from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from .. import schema, model, oauth2, email

from ..database import get_db
from ..rbac import Role, RequireWorkspaceRole, has_sufficient_role

from .tasks import verify_project_access

router = APIRouter(
    prefix="/invitations",
    tags=["Invitations"]
)


@router.post("/workspace/{workspace_id}", status_code=status.HTTP_201_CREATED, response_model=schema.WorkspaceInviteOut)
def invite_to_workspace(
    workspace_id: int,
    invitation_data: schema.WorkspaceInvitationCreate,
    background_tasks: BackgroundTasks,
    current_user: Annotated[model.Users, Depends(oauth2.get_current_active_user)],
    membership: Annotated[model.WorkspaceMember, Depends(RequireWorkspaceRole(Role.ADMIN))],
    db: Session = Depends(get_db)
):
    """Requires at least ADMIN or OWNER role in the workspace to send invites."""
    workspace = db.query(model.Workspace).filter(model.Workspace.id == workspace_id).first()

    clean_email = invitation_data.email.strip().lower()
    role_str = invitation_data.role.value if hasattr(invitation_data.role, "value") else str(invitation_data.role).lower()
    if role_str == "owner":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot invite users with the Owner role"
        )

    # Check if invited user is already a member
    invited_user = db.query(model.Users).filter(model.Users.email == clean_email).first()
    if invited_user:
        already_member = db.query(model.WorkspaceMember).filter(
            model.WorkspaceMember.workspace_id == workspace_id,
            model.WorkspaceMember.user_id == invited_user.id
        ).first()
        if already_member:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"User with email {clean_email} is already a member of this workspace"
            )

    # Check if there is already a pending invite
    pending_invite = db.query(model.WorkspaceInvitation).filter(
        model.WorkspaceInvitation.workspace_id == workspace_id,
        model.WorkspaceInvitation.invited_email == clean_email,
        model.WorkspaceInvitation.status == "pending"
    ).first()

    if pending_invite:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"An active invitation for {clean_email} is already pending"
        )

    new_invite = model.WorkspaceInvitation(
        workspace_id=workspace_id,
        invited_email=clean_email,
        invited_by=current_user.id,
        role=role_str,
        status="pending"
    )

    db.add(new_invite)
    db.commit()
    db.refresh(new_invite)

    # Send invitation email in the background
    background_tasks.add_task(
        email.send_invitation_email,
        to_email=new_invite.invited_email,
        workspace_name=workspace.name,
        role=new_invite.role,
        inviter_name=current_user.name
    )

    return new_invite


@router.get("/me", response_model=list[schema.WorkspaceInviteOut])
def get_my_invitations(
    current_user: Annotated[model.Users, Depends(oauth2.get_current_active_user)],
    db: Session = Depends(get_db)
):
    """Retrieves all pending workspace invitations sent to the current user's email."""
    invitations = db.query(model.WorkspaceInvitation).filter(
        model.WorkspaceInvitation.invited_email == current_user.email.strip().lower(),
        model.WorkspaceInvitation.status == "pending"
    ).all()

    return invitations


@router.post("/workspace/{id}/accept", response_model=schema.MessageResponse)
def accept_workspace_invitation(
    id: int,
    current_user: Annotated[model.Users, Depends(oauth2.get_current_active_user)],
    db: Session = Depends(get_db)
):
    invite = db.query(model.WorkspaceInvitation).filter(
        model.WorkspaceInvitation.id == id,
        model.WorkspaceInvitation.status == "pending"
    ).first()

    if not invite:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Pending invitation not found"
        )

    if invite.invited_email.strip().lower() != current_user.email.strip().lower():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This invitation was not sent to your email address"
        )

    # Verify workspace is active and not deleted
    workspace = db.query(model.Workspace).filter(
        model.Workspace.id == invite.workspace_id,
        model.Workspace.is_deleted == False
    ).first()
    if not workspace:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot accept invitation: Workspace has been deleted or does not exist"
        )

    # Safely add user as member if not already added
    already_member = db.query(model.WorkspaceMember).filter(
        model.WorkspaceMember.workspace_id == invite.workspace_id,
        model.WorkspaceMember.user_id == current_user.id
    ).first()

    if not already_member:
        new_member = model.WorkspaceMember(
            user_id=current_user.id,
            workspace_id=invite.workspace_id,
            role=invite.role
        )
        db.add(new_member)

    # Mark invite as accepted
    invite.status = "accepted"
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Invitation already accepted or membership already exists"
        )

    return {"message": f"Invitation accepted! You are now a {invite.role} in this workspace."}


@router.post("/workspace/{id}/reject", response_model=schema.MessageResponse)
def reject_workspace_invitation(
    id: int,
    current_user: Annotated[model.Users, Depends(oauth2.get_current_active_user)],
    db: Session = Depends(get_db)
):
    invite = db.query(model.WorkspaceInvitation).filter(
        model.WorkspaceInvitation.id == id,
        model.WorkspaceInvitation.status == "pending"
    ).first()

    if not invite:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Pending invitation not found"
        )

    if invite.invited_email != current_user.email:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This invitation was not sent to your email address"
        )

    invite.status = "rejected"
    db.commit()

    return {"message": "Invitation declined."}


@router.post("/project/{project_id}", status_code=status.HTTP_201_CREATED, response_model=schema.ProjectInviteOut)
def invite_to_project(
    project_id: int,
    invitation_data: schema.ProjectInvitationCreate,
    current_user: Annotated[model.Users, Depends(oauth2.get_current_active_user)],
    db: Session = Depends(get_db)
):
    project = db.query(model.Project).filter(
        model.Project.id == project_id,
        model.Project.is_deleted == False
    ).first()

    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Project with id {project_id} not found"
        )

    workspace = db.query(model.Workspace).filter(
        model.Workspace.id == project.workspace_id,
        model.Workspace.is_deleted == False
    ).first()

    if not workspace:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Parent workspace not found"
        )

    # Dual authorization: Workspace Owner/Admin OR Project Owner/Admin
    is_ws_owner = workspace.owner_id == current_user.id
    ws_member = db.query(model.WorkspaceMember).filter(
        model.WorkspaceMember.workspace_id == project.workspace_id,
        model.WorkspaceMember.user_id == current_user.id
    ).first()
    is_ws_admin = ws_member and has_sufficient_role(ws_member.role, Role.ADMIN)

    is_project_owner = project.owner_id == current_user.id
    proj_member = db.query(model.ProjectMember).filter(
        model.ProjectMember.project_id == project.id,
        model.ProjectMember.user_id == current_user.id
    ).first()
    is_project_admin = proj_member and proj_member.role == Role.ADMIN.value

    if not (is_ws_owner or is_ws_admin or is_project_owner or is_project_admin):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You are not authorized to invite members to this project"
        )

    clean_email = invitation_data.email.strip().lower()
    role_str = invitation_data.role.value if hasattr(invitation_data.role, "value") else str(invitation_data.role).lower()
    if role_str == "owner":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot invite users with the Owner role"
        )

    # Check if target user is already a member or owner of the project
    target_user = db.query(model.Users).filter(model.Users.email == clean_email).first()
    if target_user:
        already_member = db.query(model.ProjectMember).filter(
            model.ProjectMember.project_id == project_id,
            model.ProjectMember.user_id == target_user.id
        ).first()
        if already_member or project.owner_id == target_user.id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"User with email {clean_email} is already a member of this project"
            )

    # Check for duplicate pending invitation
    pending_invite = db.query(model.ProjectInvitation).filter(
        model.ProjectInvitation.project_id == project_id,
        model.ProjectInvitation.invited_email == clean_email,
        model.ProjectInvitation.status == "pending"
    ).first()
    if pending_invite:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"An active invitation for {clean_email} is already pending for this project"
        )

    new_invite = model.ProjectInvitation(
        project_id=project_id,
        invited_email=clean_email,
        invited_by=current_user.id,
        role=role_str,
        status="pending"
    )

    db.add(new_invite)
    db.commit()
    db.refresh(new_invite)

    return new_invite


@router.post("/project/{id}/accept", response_model=schema.MessageResponse)
def accept_project_invitation(
    id: int,
    current_user: Annotated[model.Users, Depends(oauth2.get_current_active_user)],
    db: Session = Depends(get_db)
):
    invite = db.query(model.ProjectInvitation).filter(
        model.ProjectInvitation.id == id,
        model.ProjectInvitation.status == "pending"
    ).first()

    if not invite:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Pending project invitation not found"
        )

    if invite.invited_email.strip().lower() != current_user.email.strip().lower():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This invitation was not sent to your email address"
        )

    project = db.query(model.Project).filter(
        model.Project.id == invite.project_id,
        model.Project.is_deleted == False
    ).first()
    if not project:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot accept invitation: Project has been deleted or does not exist"
        )

    workspace = db.query(model.Workspace).filter(
        model.Workspace.id == project.workspace_id,
        model.Workspace.is_deleted == False
    ).first()
    if not workspace:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot accept invitation: Parent workspace has been deleted or does not exist"
        )

    # Auto-enroll in parent workspace if not already a member
    is_ws_owner = workspace.owner_id == current_user.id
    ws_membership = db.query(model.WorkspaceMember).filter(
        model.WorkspaceMember.workspace_id == project.workspace_id,
        model.WorkspaceMember.user_id == current_user.id
    ).first()

    if not ws_membership and not is_ws_owner:
        new_ws_member = model.WorkspaceMember(
            workspace_id=project.workspace_id,
            user_id=current_user.id,
            role=Role.MEMBER.value
        )
        db.add(new_ws_member)

    # Add to project if not already a member
    already_proj_member = db.query(model.ProjectMember).filter(
        model.ProjectMember.project_id == invite.project_id,
        model.ProjectMember.user_id == current_user.id
    ).first()

    if not already_proj_member and project.owner_id != current_user.id:
        new_member = model.ProjectMember(
            user_id=current_user.id,
            project_id=invite.project_id,
            role=invite.role
        )
        db.add(new_member)

    invite.status = "accepted"
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Invitation already accepted or membership already exists"
        )

    return {"message": "Project invitation accepted! You now have access to this project."}


@router.post("/project/{id}/reject", response_model=schema.MessageResponse)
def reject_project_invitation(
    id: int,
    current_user: Annotated[model.Users, Depends(oauth2.get_current_active_user)],
    db: Session = Depends(get_db)
):
    invite = db.query(model.ProjectInvitation).filter(
        model.ProjectInvitation.id == id,
        model.ProjectInvitation.status == "pending"
    ).first()

    if not invite:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Pending project invitation not found"
        )

    if invite.invited_email.strip().lower() != current_user.email.strip().lower():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This invitation was not sent to your email address"
        )

    invite.status = "rejected"
    db.commit()

    return {"message": "Project invitation declined."}
