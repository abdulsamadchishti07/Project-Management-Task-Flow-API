from datetime import datetime
from enum import Enum
from pydantic import EmailStr, BaseModel, Field

from pydantic import ConfigDict
from typing import Optional


class WorkspaceRoleInvite(str, Enum):
    VIEWER = "viewer"
    MEMBER = "member"
    ADMIN = "admin"


class ProjectRoleInvite(str, Enum):
    MEMBER = "member"
    ADMIN = "admin"


class TaskStatus(str, Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"


class TaskPriority(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    URGENT = "urgent"


    # User
class UserOut(BaseModel):
    id: int
    email: EmailStr
    name: str
    active: bool = True
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)

class UserCreate(BaseModel):
    email: EmailStr
    name: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=8, max_length=128, description="Password must be between 8 and 128 characters")

    model_config = ConfigDict(from_attributes=True)

class UserUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=100)
    password: Optional[str] = Field(default=None, min_length=8, max_length=128, description="New password (optional)")

    model_config = ConfigDict(from_attributes=True)

    # OTP
class VerifyOTP(BaseModel):
    email: EmailStr
    otp: str = Field(min_length=6, max_length=6, pattern=r"^\d{6}$", description="6-digit verification code")

class ResendOTP(BaseModel):
    email: EmailStr

class MessageResponse(BaseModel):
    message: str

    # Token
class Token(BaseModel):
    access_token: str
    token_type: str

class TokenData(BaseModel):
    id: int | None = None


# WorkSpace 

class WorkspaceCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)

class WorkspaceOut(BaseModel):
    id: int
    name: str
    active: bool
    created_at: datetime
    owner_id: int
    owner: UserOut 

    model_config = ConfigDict(from_attributes=True)

class WorkspaceMemberOut(BaseModel):
    id: int
    user_id: int
    workspace_id: int
    role: str
    joined_at: datetime

    model_config = ConfigDict(from_attributes=True)
class WorkspaceInvitationCreate(BaseModel):
    email: EmailStr
    role: WorkspaceRoleInvite = WorkspaceRoleInvite.MEMBER

class WorkspaceInviteOut(BaseModel):
    id: int
    workspace_id: int
    invited_email: EmailStr
    role: str
    status: str
    created_at: datetime
    invited_by: int
    model_config = ConfigDict(from_attributes=True)

    # project

class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    description: Optional[str] = Field(default=None, max_length=500)
    private: Optional[bool] = False

class ProjectOut(BaseModel):
    id: int
    name: str
    description: Optional[str] = None
    active: bool
    created_at: datetime
    private: bool
    owner_id: int
    owner: UserOut 
    workspace_id: int

    model_config = ConfigDict(from_attributes=True)

class ProjectInvitationCreate(BaseModel):
    email: EmailStr
    project_id: Optional[int] = None
    role: ProjectRoleInvite = ProjectRoleInvite.MEMBER

class ProjectInviteOut(BaseModel):
    id: int
    project_id: int
    invited_email: EmailStr
    role: str
    status: str
    created_at: datetime
    invited_by: int

    model_config = ConfigDict(from_attributes=True)

# task

class TasksCreate(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    description: Optional[str] = None
    status: Optional[TaskStatus] = TaskStatus.PENDING
    priority: Optional[TaskPriority] = TaskPriority.MEDIUM
    assignee_id: Optional[int] = None
    due_date: Optional[datetime] = None

class TasksUpdate(BaseModel):
    title: Optional[str] = Field(default=None, min_length=1, max_length=255)
    description: Optional[str] = None
    status: Optional[TaskStatus] = None
    priority: Optional[TaskPriority] = None
    assignee_id: Optional[int] = None
    due_date: Optional[datetime] = None

class TasksOut(BaseModel):
    id: int
    project_id: int
    title: str
    description: Optional[str] = None
    status: str
    priority: str
    assignee_id: Optional[int] = None
    assignee: Optional[UserOut] = None
    created_at: datetime
    due_date: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)

# comments

class CommentsCreate(BaseModel):
    content: str = Field(min_length=1, max_length=2000)

class CommentsOut(BaseModel):
    id: int
    task_id: int
    user_id: int
    user: Optional[UserOut] = None
    content: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
    
    # Audit Log
class AuditLogOut(BaseModel):
    id: int
    workspace_id: int
    user_id: int
    user: Optional[UserOut] = None
    action: str
    entity_type: str
    entity_id: int
    details: Optional[str] = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
