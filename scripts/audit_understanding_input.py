#!/usr/bin/env python3
"""Audit U request composition; no generation, scene writes or Control calls."""
import argparse
import hashlib
import json
from pathlib import Path
from robot_agent_brain.config import BrainConfig
from robot_agent_brain.contracts.scene import SceneConfig
from robot_agent_brain.models.task_understanding import TaskUnderstandingRequest
from robot_agent_brain.models.prompts import TASK_UNDERSTANDING_PROMPT, build_spatial_reference_tables
from robot_agent_brain.application import BrainApplication


def size(value):
    text=value if isinstance(value,str) else json.dumps(value,ensure_ascii=False,separators=(",",":"))
    return {"chars":len(text),"utf8_bytes":len(text.encode()),"sha256":hashlib.sha256(text.encode()).hexdigest()}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--config",type=Path,required=True)
    p.add_argument("--scene",type=Path,required=True)
    p.add_argument("--output",type=Path,required=True)
    args=p.parse_args()
    config=BrainConfig.load(args.config)
    assert config.planner=="qwen" and not config.execution_enabled
    def no_platform(*args, **kwargs):
        raise RuntimeError("audit_must_not_access_platform")
    app=BrainApplication(config, platform_factory=no_platform)
    provider,pipeline=app.provider,app.pipeline
    scene=SceneConfig.model_validate_json(args.scene.read_text())
    request=TaskUnderstandingRequest(instruction="桌面有几个苹果？",
        asset_catalog=pipeline.asset_catalog,
        workspace=pipeline.workspace_context,scene_context=pipeline._understanding_scene_context(scene))
    stage=provider.build_understanding_request(request)
    content=json.loads(stage.content)
    spatial=build_spatial_reference_tables()
    result={"scope":"locally reconstructed query request, no generation; fragment chars are not tokens",
        "system_total":size(stage.prompt),"base_prompt":size(TASK_UNDERSTANDING_PROMPT.removesuffix(spatial)),
        "spatial_appendix":size(spatial),"system_asset_catalog":size(provider.asset_catalog_prompt),
        "user_total":size(stage.content),"user_fields":{key:size(value) for key,value in content.items()},
        "response_schema":size(stage.schema),"model":config.model,
        "token_note":"Use real request usage from baseline/after traces for full prompt tokens; JSON schema byte count is not assumed to equal model-visible input.",
        "asset_catalog_in_both_messages":bool(provider.asset_catalog_prompt and content.get("asset_catalog"))}
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n")
    print(json.dumps(result,ensure_ascii=False))


if __name__=="__main__":
    main()
