from pydantic import BaseModel, ConfigDict, Field


class BrainIssue(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code: str
    stage: str
    message: str
    details: dict = Field(default_factory=dict)
    clarification_question: str | None = None
    category: str = "internal"
    path: str | None = None
    value: object | None = None
    retryable: bool = False
    legacy_code: str | None = None


class BrainError(ValueError):
    def __init__(self, code, stage, message, *, category="semantic", path=None,
                 value=None, retryable=False, legacy_code=None, **details):
        self.issue = BrainIssue(code=code, stage=stage, message=message, details=details,
                                category=category, path=path, value=value,
                                retryable=retryable, legacy_code=legacy_code)
        super().__init__(f"{code}: {message}")


class SceneCommitRejected(ValueError):
    """Authoritative rejection AND an unchanged-world readback; safe to retain state."""
