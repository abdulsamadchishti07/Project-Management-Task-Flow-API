from .database import Base
from sqlalchemy import Integer, Column, String, Boolean, text, ForeignKey, UniqueConstraint

from sqlalchemy.sql.sqltypes import TIMESTAMP
from sqlalchemy.orm import relationship


class Users(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, nullable=False)
    email = Column(String, nullable=False, unique=True)
    name = Column(String, nullable=False)
    password = Column(String, nullable=False)
    active = Column(Boolean, server_default="False", nullable=False)
    verification_otp = Column(String, nullable=True)
    otp_expires_at = Column(TIMESTAMP(timezone=True), nullable=True)
    token_version = Column(Integer, server_default="1", default=1, nullable=False)
    created_at = Column(TIMESTAMP(timezone=True), nullable=False, server_default=text("now()"))


class Workspace(Base):
    __tablename__ = "workspaces"

    id = Column(Integer, primary_key=True, nullable=False)
    name = Column(String, nullable=False)
    active = Column(Boolean, server_default="True", nullable=False)
    is_deleted = Column(Boolean, default=False, server_default="false", nullable=False)
    deleted_at = Column(TIMESTAMP(timezone=True), nullable=True)
    created_at = Column(TIMESTAMP(timezone=True), nullable=False, server_default=text("now()"))

    owner_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    owner = relationship("Users")


class WorkspaceMember(Base):
    __tablename__ = "workspace_members"

    id = Column(Integer, primary_key=True, nullable=False)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    workspace_id = Column(Integer, ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False)
    role = Column(String, nullable=False, server_default="member")
    joined_at = Column(TIMESTAMP(timezone=True), nullable=False, server_default=text("now()"))

    __table_args__ = (
        UniqueConstraint("user_id", "workspace_id", name="unique_workspace_member"),
    )


class WorkspaceInvitation(Base):
    __tablename__ = "workspace_invitations"

    id = Column(Integer, primary_key=True, nullable=False)
    workspace_id = Column(Integer, ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False)
    invited_email = Column(String, nullable=False)
    invited_by = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    role = Column(String, nullable=False, server_default="member")
    status = Column(String, nullable=False, server_default="pending")
    created_at = Column(TIMESTAMP(timezone=True), nullable=False, server_default=text("now()"))


class Project(Base):
    __tablename__ = "projects"

    id = Column(Integer, primary_key=True, nullable=False)
    workspace_id = Column(Integer, ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False)
    name = Column(String, nullable=False)
    description = Column(String, nullable=True)
    active = Column(Boolean, server_default="true", nullable=False)
    is_deleted = Column(Boolean, default=False, server_default="false", nullable=False)
    deleted_at = Column(TIMESTAMP(timezone=True), nullable=True)
    created_at = Column(TIMESTAMP(timezone=True), nullable=False, server_default=text("NOW()"))
    private = Column(Boolean, server_default="false", nullable=False)

    owner_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    owner = relationship("Users")


class ProjectMember(Base):
    __tablename__ = "project_members"

    id = Column(Integer, primary_key=True, nullable=False)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    project_id = Column(Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    role = Column(String, nullable=False, server_default="member")
    joined_at = Column(TIMESTAMP(timezone=True), nullable=False, server_default=text("now()"))

    __table_args__ = (
        UniqueConstraint("user_id", "project_id", name="unique_project_member"),
    )


class ProjectInvitation(Base):
    __tablename__ = "project_invitations"

    id = Column(Integer, primary_key=True, nullable=False)
    project_id = Column(Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    invited_email = Column(String, nullable=False)
    invited_by = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    role = Column(String, nullable=False, server_default="member")
    status = Column(String, nullable=False, server_default="pending")
    created_at = Column(TIMESTAMP(timezone=True), nullable=False, server_default=text("now()"))


class Tasks(Base):
    __tablename__ = "tasks"

    id = Column(Integer, primary_key=True, nullable=False)
    project_id = Column(Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    title = Column(String, nullable=False)
    description = Column(String, nullable=True)
    status = Column(String, server_default="pending", nullable=False)
    priority = Column(String, server_default="medium", nullable=False)
    is_deleted = Column(Boolean, default=False, server_default="false", nullable=False)
    deleted_at = Column(TIMESTAMP(timezone=True), nullable=True)
    assignee_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(TIMESTAMP(timezone=True), nullable=False, server_default=text("now()"))
    due_date = Column(TIMESTAMP(timezone=True), nullable=True)

    assignee = relationship("Users")


class Comments(Base):
    __tablename__ = "comments"

    id = Column(Integer, primary_key=True, nullable=False)
    task_id = Column(Integer, ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    content = Column(String, nullable=False)
    is_deleted = Column(Boolean, default=False, server_default="false", nullable=False)
    deleted_at = Column(TIMESTAMP(timezone=True), nullable=True)
    created_at = Column(TIMESTAMP(timezone=True), nullable=False, server_default=text("now()"))

    user = relationship("Users")


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id = Column(Integer, primary_key=True, nullable=False)
    workspace_id = Column(Integer, ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    action = Column(String, nullable=False)  # e.g., "TASK_CREATED", "PROJECT_DELETED", "STATUS_UPDATED"
    entity_type = Column(String, nullable=False)  # "workspace", "project", "task", "comment"
    entity_id = Column(Integer, nullable=False)
    details = Column(String, nullable=True)
    created_at = Column(TIMESTAMP(timezone=True), nullable=False, server_default=text("now()"))

    user = relationship("Users")
    workspace = relationship("Workspace")