from typing import Annotated, Optional
import logging
from fastapi import FastAPI, Depends, status, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import text
from .routers import auth, users, workspaces, project, tasks, comments, invitations
from . import model, oauth2
from .database import get_db

logger = logging.getLogger(__name__)

app = FastAPI(title="TaskFlow API", version="1.0.0")

app.include_router(users.router)
app.include_router(auth.router)
app.include_router(workspaces.router)
app.include_router(project.router)
app.include_router(tasks.router)
app.include_router(comments.router)
app.include_router(invitations.router)


@app.get("/")
def root(current_user: Annotated[Optional[model.Users], Depends(oauth2.get_optional_current_user)] = None):
    if current_user is None:
        return {"message": "Welcome to TaskFlow!"}
    return {"message": f"Welcome to TaskFlow, {current_user.name}!"}


@app.get("/health", tags=["Health"])
def health_check():
    """Liveness probe: verifies the application server process is running."""
    return {"status": "healthy"}


@app.get("/ready", tags=["Health"])
def readiness_check(db: Session = Depends(get_db)):
    """Readiness probe: verifies downstream database connectivity."""
    try:
        db.execute(text("SELECT 1"))
        return {"status": "ready"}
    except Exception as e:
        logger.error(f"Readiness check failed: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database connection unavailable"
        )
