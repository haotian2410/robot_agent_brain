from pydantic import BaseModel, ConfigDict, Field


class BrainIssue(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code: str
    stage: str
    message: str
    details: dict = Field(default_factory=dict)
    clarification_question: str | None = None


class BrainError(ValueError):
    def __init__(self, code, stage, message, **details):
        self.issue = BrainIssue(code=code, stage=stage, message=message, details=details)
        super().__init__(f"{code}: {message}")
