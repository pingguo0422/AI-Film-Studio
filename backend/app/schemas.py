from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field
from datetime import datetime

class ProjectCreate(BaseModel):
    code: str = Field(min_length=2, max_length=32, pattern=r"^[A-Z][A-Z0-9_-]+$")
    name: str = Field(min_length=1, max_length=200)
    description: str | None = None

class ProjectRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    code: str
    name: str
    description: str | None
    status: str
    created_at: datetime
