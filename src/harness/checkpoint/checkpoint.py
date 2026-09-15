from pydantic import BaseModel, Field

class Checkpoint(BaseModel):
    thread_id: str 
    message: list[dict] = Field(default_factory = list)
    step: int = 0
    status: str = "running"
    pending_tool: dict | None = None
    user_id: str | None = None
    completed_calls: dict[str, str] = Field(default_factory = dict)