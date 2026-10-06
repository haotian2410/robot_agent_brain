import json
from pathlib import Path
from ..contracts.turn import BrainTurn


class ReplayProvider:
    """Exact-input replay of validated turns, not natural-language understanding."""
    def __init__(self, path):
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        self.turns = {}
        for record in data:
            instruction = record["instruction"]
            if instruction in self.turns:
                raise ValueError("replay_duplicate_instruction")
            self.turns[instruction] = BrainTurn.model_validate(record["turn"])
        self.calls = []

    def understand_turn(self, request):
        if request.instruction not in self.turns:
            raise ValueError("replay_instruction_missing: exact fixture input required")
        self.calls.append({"stage":"task_understanding", "provider":"replay", "status":"succeeded"})
        return self.turns[request.instruction].model_copy(deep=True)
