"""Read-only local service/resource probe. Does not load or modify a world."""
import argparse
import json
import httpx
from robot_agent_brain.config import BrainConfig
from robot_agent_brain.web.assets import check_ols
from robot_agent_brain.web.gateway import GatewayScenePlatformAdapter


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', default='config/webeditor.json')
    parser.add_argument('--browser-id')
    args = parser.parse_args()
    config = BrainConfig.load(args.config)
    result = {"executed":False,"browser":"not_checked_without_explicit_browser_id"}
    with httpx.Client(timeout=5,trust_env=False) as client:
        for key, operation in {
            "qwen":lambda:client.get(config.base_url+'/models').raise_for_status().json(),
            "assets":lambda:check_ols(client,'http://127.0.0.1:8000',config.asset_library_root),
            "agent":lambda:client.get('http://127.0.0.1:8500/health').raise_for_status().json(),
        }.items():
            try:
                result[key] = operation()
            except Exception as exc:
                result[key] = {"ready":False,"error":str(exc)}
        if args.browser_id:
            gateway = GatewayScenePlatformAdapter('http://127.0.0.1:8099',args.browser_id,client=client)
            try:
                result['browser'] = gateway.capabilities()
                scene = gateway.read_live()
                result['browser']['scene_id'] = scene.scene_id
            except Exception as exc:
                result['browser'] = {"ready":False,"error":str(exc)}
    print(json.dumps(result,ensure_ascii=False,indent=2))


if __name__ == '__main__':
    main()
