"""Read-only real U audit: no scene publication, dispatch, or model retries."""
import argparse
import json
import time
from pathlib import Path
import httpx
from robot_agent_brain.config import BrainConfig
from robot_agent_brain.models.qwen_http import QwenHTTPProvider
from robot_agent_brain.pipeline import BrainPipeline


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args()
    config = BrainConfig.load(args.config)
    args.output_dir.mkdir(parents=True, exist_ok=False)
    requests, records = [], []
    def capture(request):
        if request.method == 'POST':
            requests.append(json.loads(request.content))
    with httpx.Client(timeout=120, event_hooks={'request': [capture]}) as client:
        response = client.get(config.base_url.rstrip('/') + '/models')
        response.raise_for_status()
        provider = QwenHTTPProvider(config.base_url, response.json()['data'][0]['id'], client=client,
            live_catalog=True, understanding_wire_format='compact_v1')
        pipeline = BrainPipeline(provider, config.load_assets(), registered_profiles=['fixture_single','fixture_dual'])
        unbound = {'locked': False, 'decision': None, 'deployment': None, 'robot_setup_revision': 0,
                   'first_robot_mode_turn_id': None}
        dual = {'locked': True, 'decision': {'mode': 'dual', 'profile_id': 'fixture_dual', 'locked': True},
                'deployment': {'mode': 'dual', 'profile_id': 'fixture_dual'}, 'robot_setup_revision': 1,
                'first_robot_mode_turn_id': 'fixture-robot'}
        cases = [
            ('after_layout', '已经完成桌面布局，现在使用已注册的fixture_dual双臂配置，左臂抓苹果，右臂抓香蕉', unbound),
            ('explicit_setup', '将会话配置为已注册的fixture_dual双臂模式', unbound),
            ('locked_change', '将模式改成fixture_single单臂配置', dual),
            ('dual_one_arm', '用左臂抓起苹果', dual),
            ('same_container', '用左臂把苹果放进篮子，用右臂把香蕉放进同一个篮子', dual),
            ('explicit_order', '先用左臂抓起苹果，完成后再用右臂抓起香蕉', dual),
            ('direction_distance', '用左臂将苹果向右推五厘米', dual),
        ]
        for name, instruction, context in cases:
            start = time.monotonic()
            offset, wire_offset = len(provider.calls), len(requests)
            row = dict(case=name, instruction=instruction, mode_context=context,
                       scene_published=False, control_called=False)
            try:
                turn = pipeline.understand_turn(instruction, mode_context=context)
                row['canonical'] = turn.model_dump(mode='json')
                row['schema_accepted'] = turn.status == 'accepted'
                if name == 'locked_change':
                    row['expected_handling'] = 'Python rejects a different mode; model parsing is not authorization'
                elif name == 'same_container' and turn.task_intent:
                    row['no_implicit_dependencies'] = all(not op.depends_on for op in turn.task_intent.operations)
                elif name == 'explicit_order' and turn.task_intent:
                    ops = turn.task_intent.operations
                    row['explicit_dependency_preserved'] = len(ops)==2 and ops[1].depends_on == [ops[0].operation_id]
            except Exception as error:
                row.update(schema_accepted=False, error=str(error), error_type=type(error).__name__)
            row.update(elapsed_seconds=time.monotonic()-start, calls=provider.calls[offset:],
                       wire_requests=requests[wire_offset:], raw_values=provider.last_raw_values)
            (args.output_dir/(name+'.json')).write_text(json.dumps(row, ensure_ascii=False, indent=2, default=str))
            records.append({key: value for key,value in row.items() if key not in {'canonical','calls','wire_requests','raw_values'}})
            print(name, row['schema_accepted'], row['elapsed_seconds'], flush=True)
    (args.output_dir/'report.json').write_text(json.dumps(records, ensure_ascii=False, indent=2))

if __name__ == '__main__':
    main()
