import json
import uuid
from pathlib import Path
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator
from .adapters.artifact_writer import ArtifactWriter


class Expected(BaseModel):
    model_config = ConfigDict(extra="forbid")
    turn_kind: str | None = None
    run_status: Literal["success", "blocked", "failed"] | None = None
    artifacts: list[str] = Field(default_factory=list)
    absent_artifacts: list[str] = Field(default_factory=list)
    assertions: dict = Field(default_factory=dict)


class BatchCase(BaseModel):
    model_config = ConfigDict(extra="forbid")
    case_id: str
    session_group: str
    instruction: str
    scene: str | None = None
    expected: Expected = Field(default_factory=Expected)
    continue_after_failure: bool = False


class BatchSession(BaseModel):
    """The small user-facing format: one scene and an ordered instruction list."""
    model_config = ConfigDict(extra="forbid")
    name: str | None = None
    scene: str | None = None
    instructions: list[str] = Field(min_length=1)

    @field_validator("instructions")
    @classmethod
    def instructions_must_be_nonempty(cls, value):
        if any(not isinstance(item, str) or not item.strip() for item in value):
            raise ValueError("batch_instruction_required")
        return value


def load_batch_input(path):
    """Load the simple JSON format, while retaining the historical JSONL format."""
    path = Path(path).resolve()
    text = path.read_text(encoding="utf-8")
    try:
        document = json.loads(text)
    except json.JSONDecodeError:
        cases = [BatchCase.model_validate(json.loads(line)) for line in text.splitlines() if line.strip()]
        return {"kind": "legacy", "path": path, "cases": cases}
    if isinstance(document, dict) and isinstance(document.get("sessions"), list):
        sessions = [BatchSession.model_validate(item) for item in document["sessions"]]
        names = set()
        normalized = []
        for index, session in enumerate(sessions, 1):
            name = session.name or f"session-{index:03d}"
            if name in names:
                raise ValueError("batch_duplicate_session_name")
            names.add(name)
            normalized.append(session.model_copy(update={"name": name}))
        return {"kind": "sessions", "path": path, "sessions": normalized}
    if isinstance(document, list):
        cases = [BatchCase.model_validate(item) for item in document]
        return {"kind": "legacy", "path": path, "cases": cases}
    raise ValueError("batch_input_requires_sessions_or_jsonl")


def run_batch(app, path):
    loaded = load_batch_input(path)
    path = loaded["path"]
    if loaded["kind"] == "sessions":
        cases = []
        for session in loaded["sessions"]:
            for turn, instruction in enumerate(session.instructions, 1):
                cases.append(BatchCase(case_id=f"{session.name}-{turn:04d}", session_group=session.name,
                                       instruction=instruction, scene=session.scene if turn == 1 else None))
    else:
        cases = loaded["cases"]
    if len({case.case_id for case in cases}) != len(cases):
        raise ValueError("batch_duplicate_case_id")
    sessions, failed_groups, results = {}, set(), []
    for case in cases:
        if case.session_group in failed_groups and not case.continue_after_failure:
            results.append({"case_id":case.case_id,"status":"skipped","reason":"session dependency failed"})
            continue
        session_id = sessions.setdefault(case.session_group, uuid.uuid4().hex)
        scene_path = (path.parent / case.scene).resolve() if case.scene else None
        report = app.handle(case.instruction, session_id=session_id, scene_path=scene_path)
        failures = []
        expected = case.expected
        for field in ("turn_kind", "run_status"):
            if getattr(expected,field) is not None and getattr(report,field) != getattr(expected,field):
                failures.append(field)
        for key in expected.artifacts:
            if key not in report.artifacts or not Path(report.artifacts[key]).is_file():
                failures.append("missing artifact: " + key)
        for key in expected.absent_artifacts:
            if key in report.artifacts:
                failures.append("unexpected artifact: " + key)
        values = report.model_dump(mode="json")
        for dotted, wanted in expected.assertions.items():
            actual = values
            for component in dotted.split("."):
                actual = actual.get(component) if isinstance(actual, dict) else None
            if actual != wanted:
                failures.append(dotted)
        if report.run_status != "success" or failures:
            failed_groups.add(case.session_group)
        passed = not failures and (report.run_status == "success" or expected.run_status == report.run_status)
        results.append({"case_id":case.case_id,"status":"passed" if passed else "failed",
                        "failures":failures,"report":values})
    summary = {"provider":app.config.provider,"cases":results,
               "totals":{name:sum(r["status"] == name for r in results) for name in ("passed","failed","skipped")}}
    directory = Path(app.config.output_dir).resolve() / ("batch-" + uuid.uuid4().hex)
    directory.mkdir(parents=True)
    ArtifactWriter._write(directory / "summary.json", summary)
    return summary, directory / "summary.json"
