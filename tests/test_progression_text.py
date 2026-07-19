import bot.agent.nodes as nodes


ROUTINE = """
DIA 1 (Lunes)
• Press banca: 3x8-10 @ 40 kg
• Press banca cerrado: 3x8-10 @ 30 kg
• Plancha: 3x30 seg
""".strip()


class FakeStore:
    def __init__(self):
        self.targets = {
            "Press banca": {
                "next_weight": 42.5,
                "next_reps": "8-10",
                "next_sets": 4,
                "basis": "completo",
            },
            "Plancha": {
                "next_weight": 0,
                "next_reps": "40 seg",
                "next_sets": 3,
                "basis": "sube tiempo",
            },
        }

    def get_progression_target(self, user_id, name):
        return self.targets.get(name)


def test_apply_progression_updates_only_exact_exercise(monkeypatch):
    monkeypatch.setattr(nodes, "_store", FakeStore())

    updated = nodes.apply_progression_to_routine_text(ROUTINE, "user-1")

    assert "• Press banca: 4x8-10 @ 42.5 kg" in updated
    assert "• Press banca cerrado: 3x8-10 @ 30 kg" in updated


def test_apply_progression_preserves_time_unit_and_zero_weight(monkeypatch):
    monkeypatch.setattr(nodes, "_store", FakeStore())

    updated = nodes.apply_progression_to_routine_text(ROUTINE, "user-1")

    assert "• Plancha: 3x40 seg" in updated
    assert "Plancha: 3x40 seg @ 0 kg" not in updated
    assert "seg seg" not in updated
