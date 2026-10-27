from fastapi import APIRouter, Depends, HTTPException, status, Response, BackgroundTasks
from sqlalchemy.orm import Session

from .. import model, schema, utils, oauth2, email
from ..database import get_db

from typing import Annotated
from datetime import datetime, timedelta, timezone

import secrets
from ..redis_client import RateLimiter



router = APIRouter(
    prefix="/user",
    tags=["Users"]
)

@router.post("/", status_code=status.HTTP_201_CREATED, response_model=schema.UserOut)
def create_user(
    user: schema.UserCreate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db)
):
    clean_email = user.email.strip().lower()
    existing_email = db.query(model.Users).filter(model.Users.email == clean_email).first()
    if existing_email:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"User with email {user.email} already exists.",
        )

    hashed_password = utils.hash(user.password)

    # Generate cryptographically secure 6-digit OTP with 10-minute expiry
    otp = f"{secrets.randbelow(900000) + 100000}"
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=10)

    new_user = model.Users(
        email=clean_email,
        name=user.name.strip(),
        password=hashed_password,
        active=False,
        verification_otp=otp,
        otp_expires_at=expires_at,
        token_version=1
    )

    db.add(new_user)
    db.commit()
    db.refresh(new_user)

    # Send verification email asynchronously in the background
    background_tasks.add_task(email.send_otp_email, new_user.email, otp)

    return new_user


@router.post(
    "/verify-otp",
    response_model=schema.MessageResponse,
    dependencies=[
        Depends(
            RateLimiter(
                times=5,
                seconds=300,
                key_prefix="rate_verify_otp"
            )
        )
    ]
)
def verify_otp(
    payload: schema.VerifyOTP,
    db: Session = Depends(get_db)
):
    clean_email = payload.email.strip().lower()
    user = db.query(model.Users).filter(model.Users.email == clean_email).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User with this email does not exist."
        )

    if user.active:
        return {"message": "Account is already verified and active. You can log in."}

    if not user.verification_otp or user.verification_otp != payload.otp:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid verification code."
        )

    if user.otp_expires_at:
        expires_at = user.otp_expires_at
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        if datetime.now(timezone.utc) > expires_at:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Verification code has expired. Please request a new one."
            )

    user.active = True
    user.verification_otp = None
    user.otp_expires_at = None
    db.commit()

    return {"message": "Email verified successfully! Your account is now active. You can log in."}


@router.post(
    "/resend-otp", 
    response_model=schema.MessageResponse, 
    dependencies=[
        Depends(
            RateLimiter(
                times=3, 
                seconds=300, 
                key_prefix="rate_resend_otp"
            )
        )
    ]
)
def resend_otp(
    payload: schema.ResendOTP,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db)
):
    clean_email = payload.email.strip().lower()
    user = db.query(model.Users).filter(model.Users.email == clean_email).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User with this email does not exist."
        )

    if user.active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Account is already verified and active."
        )

    otp = f"{secrets.randbelow(900000) + 100000}"
    user.verification_otp = otp
    user.otp_expires_at = datetime.now(timezone.utc) + timedelta(minutes=10)
    db.commit()

    background_tasks.add_task(email.send_otp_email, user.email, otp)

    return {"message": "A new verification code has been sent to your email."}


@router.get("/me", response_model=schema.UserOut)
def read_user_me(
    current_user: Annotated[model.Users, Depends(oauth2.get_current_active_user)],
):
    return current_user

@router.get("/{id}", response_model=schema.UserOut)
def get_user(
    id: int,
    current_user: Annotated[model.Users, Depends(oauth2.get_current_active_user)],
    db: Session = Depends(get_db)
):
    """
    Retrieves user profile. 
    Users can view their own profile or teammate profiles from shared workspaces.
    """
    user = db.query(model.Users).filter(model.Users.id == id).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"User with id {id} does not exist"
        )

    # Self lookup is always allowed
    if id == current_user.id:
        return user

    # Check if current user and target user share any workspace
    my_ws_ids = {
        w.id for w in db.query(model.Workspace.id).filter(
            (model.Workspace.owner_id == current_user.id) |
            (model.Workspace.id.in_(
                db.query(model.WorkspaceMember.workspace_id).filter(model.WorkspaceMember.user_id == current_user.id)
            ))
        ).filter(model.Workspace.is_deleted == False).all()
    }

    target_shares_ws = db.query(model.Workspace).filter(
        model.Workspace.id.in_(my_ws_ids),
        (model.Workspace.owner_id == id) |
        (model.Workspace.id.in_(
            db.query(model.WorkspaceMember.workspace_id).filter(model.WorkspaceMember.user_id == id)
        ))
    ).first()

    if not target_shares_ws:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can only view profiles of users you share a workspace with."
        )

    return user


@router.put("/{id}", response_model=schema.UserOut)
def update_user(
    id: int,
    user_update: schema.UserUpdate,
    current_user: Annotated[model.Users, Depends(oauth2.get_current_active_user)],
    db: Session = Depends(get_db)
):
    user_query = db.query(model.Users).filter(model.Users.id == id)
    user = user_query.first()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"User with id {id} does not exist"
        )
        
    if user.id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You are not allowed to perform this Action."
        )

    update_data = {}
    if user_update.name is not None:
        update_data["name"] = user_update.name.strip()
    if user_update.password is not None:
        update_data["password"] = utils.hash(user_update.password)
        update_data["token_version"] = (user.token_version or 1) + 1

    if update_data:
        user_query.update(update_data, synchronize_session=False)
        db.commit()
        db.refresh(user)
    return user


@router.delete("/{id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_user(
    id: int,
    current_user: Annotated[model.Users, Depends(oauth2.get_current_active_user)],
    db: Session = Depends(get_db)
):
    user = db.query(model.Users).filter(model.Users.id == id).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"User with id {id} does not exist"
        )
    if user.id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You are not allowed to perform this Action."
        )
    # Soft deactivation preserves workspace ownership and audit log history
    user.active = False
    user.token_version = (user.token_version or 1) + 1
    user.verification_otp = None
    user.otp_expires_at = None
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)