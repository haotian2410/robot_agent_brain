"""Export schemas and deterministic, synthetic wire fixtures (no asset files)."""
import argparse
from pathlib import Path
from robot_agent_brain.contracts.scene import SceneConfig
from robot_agent_brain.web.protocol import StartTask, SessionRequest, digest
from robot_agent_brain.web.gateway import durable_json


def export(directory):
    directory = Path(directory)
    for name, model in (("start_task",StartTask),("session",SessionRequest),("scene",SceneConfig)):
        durable_json(directory/(name+'.schema.json'),model.model_json_schema())
    scene = SceneConfig(scene_schema_version=1,scene_id=1,scene_version=1,scene_name="synthetic-wire-fixture",objects=[])
    # Wire-valid empty Scene, NOT a production UR5e scene or a successful robot demo.
    scene_payload = scene.model_dump(mode="json")
    start = StartTask(command="查询苹果数量",scene=scene_payload,sessionID="fixture-session",clientRequestID="fixture-request",
        browserID="fixture-browser",sceneDigest=digest(scene_payload))
    durable_json(directory/'start_task.json',start.model_dump(mode='json'))
    durable_json(directory/'task_queued.json',{"taskID":1,"state":"已进入队列","code":0})
    durable_json(directory/'clarification.json',{"taskID":1,"outcome":"clarification_required","executed":False,
        "reply":"请指定要操作哪个苹果？","artifacts":{}})
    durable_json(directory/'commit_world.json',{"transactionID":"fixture-transaction","browserID":"fixture-browser",
        "expected":{"scene_id":1,"scene_version":1,"sceneDigest":digest(scene)},
        "scene":scene.model_copy(update={"scene_version":2}).model_dump(mode='json')})
    durable_json(directory/'commit_receipt.json',{"transactionID":"fixture-transaction","browserID":"fixture-browser",
        "status":"committed","scene_id":1,"scene_version":2,
        "sceneDigest":digest(scene.model_copy(update={"scene_version":2})),"rejected_objects":[]})
    durable_json(directory/'conflict.json',{"error":{"code":"idempotency_conflict","message":"idempotency_conflict"}})
    return directory


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir',default='var/webeditor/contract')
    print(export(parser.parse_args().output_dir).resolve())
