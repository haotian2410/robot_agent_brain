"""Explicit initialization qualifier; it is not a runtime platform switch."""
import re


def split_initial_robot(instruction):
    # Both forms are initialization qualifiers when the session is still an
    # empty bootstrap.  ``设置为`` must not be treated as a runtime platform
    # switch; the application applies the same empty-session guard as the
    # traditional ``使用`` form.
    match = re.match(
        r'^\s*(?:(?:使用|用)\s*([A-Za-z][A-Za-z0-9_-]*)|'
        r'(?:把|将)\s*机械臂\s*(?:设置为|设为|切换为)\s*([A-Za-z][A-Za-z0-9_-]*))'
        r'(?:\s*机械臂)?\s*(?:[，,:：]\s*(?:然后|再|接着)?\s*)?'
        r'(?=把|将|来|在|增加|生成|抓|拿|放|先)', instruction)
    if match is None:
        return None, instruction
    name = match.group(1) or match.group(2)
    remainder = instruction[match.end():].strip()
    if remainder.startswith('来'):
        remainder = remainder[1:].strip()
    return name.casefold(), remainder


def recover_initial_robot_name(session, command, assembly, max_failed_turns=5):
    """Fill only an unexecuted initialization model slot, never a platform switch.

    The user's new token must resolve exactly in the live arm catalog. Keep the
    original task verbatim; no model is allowed to invent a replacement task.
    Return evidence for normal understanding/validation, not execution authority.
    """
    memory = getattr(session, 'conversation_memory', None)
    chain = getattr(memory, 'active_failure_chain', None)
    if assembly is None or chain is None or chain.state != 'waiting_user':
        return None
    if len(chain.failed_user_turn_ids) >= max_failed_turns:
        return None
    if any(step.status != 'rejected' or step.confirmed_effects or step.control_run_ids
           or step.instruction != chain.root_instruction for step in chain.step_ledger):
        return None
    if (getattr(session, 'sync_state', None) != 'synchronized'
            or getattr(session, 'session_phase', None) != 'setup'
            or getattr(session, 'original_scene_manifest', None) is not None
            or getattr(session, 'platform_object_ids', None)):
        return None
    scene = getattr(session, 'scene', None)
    if scene is not None and (scene.scene_id != 0 or scene.objects):
        return None
    root = next((turn for turn in memory.recent_turns
                 if turn.turn_id == chain.root_failure_turn_id), None)
    if (root is None or root.final_error_code != 'robot_asset_unknown'
            or root.executed
            or root.effect_evidence.scene_effect != 'none_confirmed'
            or root.effect_evidence.execution_effect != 'not_started'):
        return None
    old_name, task = split_initial_robot(chain.root_instruction)
    if old_name is None or not task or not re.fullmatch(r'[A-Za-z][A-Za-z0-9_-]*', command.strip()):
        return None
    try:
        selected = assembly.resolve(command.strip(), role='arm')
    except ValueError:
        return None
    effective = f'使用 {selected.semantic_name} {task}'
    return {
        'raw_current_user_text': command,
        'source_turn_ids': [root.turn_id],
        'base_instruction': chain.root_instruction,
        'effective_instruction': effective,
        'accepted_amendments': [{'field': 'initial_robot_asset', 'value': selected.semantic_name}],
        'field_sources': {'initial_robot_asset': 'current'},
        'superseded_fields': {'initial_robot_asset': old_name},
        'scope': 'failed_step',
    }
