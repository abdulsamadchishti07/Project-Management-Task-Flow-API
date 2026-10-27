from datetime import datetime, timedelta, timezone
from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer

from jose import JWTError, jwt
from sqlalchemy.orm import Session

from . import model
from .config import settings

from .database import get_db

SECRET_KEY = settings.secret_key
ALGORITHM = settings.algorithm
ACCESS_TOKEN_EXPIRE_MINUTES = settings.access_token_expire_minutes

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="login")


def create_access_token(data: dict, expires_delta: timedelta | None = None) -> str:
    to_encode = data.copy()

    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)

    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt


async def get_current_user(
    token: Annotated[str, Depends(oauth2_scheme)],
    db: Annotated[Session, Depends(get_db)],
) -> model.Users:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id_raw = payload.get("sub")
        if user_id_raw is None:
            raise credentials_exception
        user_id = int(user_id_raw)
        token_ver = payload.get("ver")
    except (JWTError, ValueError, TypeError):
        raise credentials_exception

    user = db.query(model.Users).filter(model.Users.id == user_id).first()
    if user is None:
        raise credentials_exception

    if token_ver is None or token_ver != user.token_version:
        raise credentials_exception

    return user


async def get_current_active_user(
    current_user: Annotated[model.Users, Depends(get_current_user)],
) -> model.Users:
    if not current_user.active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Inactive user",
        )
    return current_user


oauth2_scheme_optional = OAuth2PasswordBearer(tokenUrl="login", auto_error=False)


async def get_optional_current_user(
    token: Annotated[str | None, Depends(oauth2_scheme_optional)],
    db: Annotated[Session, Depends(get_db)],
) -> model.Users | None:
    """Optional authentication: returns the User if valid token is provided, or None if guest."""
    if not token:
        return None
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id_raw = payload.get("sub")
        if user_id_raw is None:
            return None
        user_id = int(user_id_raw)
        token_ver = payload.get("ver")
        user = db.query(model.Users).filter(model.Users.id == user_id).first()
        if not user or not user.active:
            return None
        if token_ver is None or token_ver != user.token_version:
            return None
        return user
    except (JWTError, ValueError, TypeError):
        return None
