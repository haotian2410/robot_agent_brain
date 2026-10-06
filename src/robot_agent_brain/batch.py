import json
import uuid
from pathlib import Path
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field
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


def run_batch(app, path):
    path = Path(path).resolve()
    cases = [BatchCase.model_validate(json.loads(line)) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
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
