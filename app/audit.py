from typing import Optional
from sqlalchemy.orm import Session

import logging
from . import model

logger = logging.getLogger(__name__)


def log_activity(
    db: Session,
    workspace_id: int,
    user_id: int,
    action: str,
    entity_type: str,
    entity_id: int,
    details: Optional[str] = None
):
    """
    Stages an immutable audit log entry in the current database session.
    Commits atomically with the caller's business transaction.
    """
    audit_entry = model.AuditLog(
        workspace_id=workspace_id,
        user_id=user_id,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        details=details
    )
    db.add(audit_entry)
