from typing import Annotated
from fastapi import APIRouter, Depends, HTTPException, status

from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session

from .. import database, model, oauth2, schema, utils
from ..redis_client import RateLimiter

router = APIRouter(
    tags=["Authentication"]
)


@router.post(
    "/login",
    response_model=schema.Token, 
    dependencies=[
        Depends(
            RateLimiter(
                times=5, 
                seconds=60, 
                key_prefix="rate_login"
            )
        )
    ]
)
def login(
    user_credential: Annotated[OAuth2PasswordRequestForm, Depends()],
    db: Session = Depends(database.get_db),
):
    email_clean = user_credential.username.strip().lower()
    user = db.query(model.Users).filter(model.Users.email == email_clean).first()

    if not user or not utils.verify_password(user_credential.password, user.password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid Credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not user.active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Please verify your email with the OTP code before logging in."
        )

    access_token = oauth2.create_access_token(
        data={"user_id": user.id, "sub": str(user.id), "ver": user.token_version}
    )

    return {"access_token": access_token, "token_type": "bearer"}


@router.post("/logout", response_model=schema.MessageResponse)
def logout(
    current_user: Annotated[model.Users, Depends(oauth2.get_current_active_user)],
    db: Session = Depends(database.get_db)
):
    """Bumps token_version, immediately invalidating all active sessions for this user."""
    current_user.token_version = (current_user.token_version or 1) + 1
    db.commit()
    return {"message": "Successfully logged out. All active sessions revoked."}


