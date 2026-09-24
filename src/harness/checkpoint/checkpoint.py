from pydantic import BaseModel, Field

class Checkpoint(BaseModel):
    thread_id: str 
    message: list[dict] = Field(default_factory = list)
    step: int = 0
    status: str = "running"
    pending_tool: dict | None = None
    user_id: str | None = None
    completed_calls: dict[str, str] = Field(default_factory = dict)
    # The model/effort the run started with, so /approve resumes with the same.
    model: str | None = None
    effort: str | None = None    # Connectors the user had on for this conversation, so a resume exposes
    # the same tools.
    connectors: list[str] = Field(default_factory = list)
    # Prompt-injection state (taint, events) so a resume keeps the step-up.
    security: dict = Field(default_factory = dict)
    # The conversation this run belongs to (conversations.id), so /approve can
    # resume with its context and append to its transcript. None = stateless run.
    conversation_id: str | None = None
    # Index into `message`: everything from here on is not yet in the
    # conversation transcript. See db.models.Thread.persisted_upto.
    persisted_upto: int = 0
