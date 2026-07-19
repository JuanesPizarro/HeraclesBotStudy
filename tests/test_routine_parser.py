from bot.handlers.web_api import _extract_day_section, _parse_session_exercises


ROUTINE = """
RUTINA GENERAL

DÍA 1 - EMPUJE (Lunes)
• Press banca: 3x8-10 @ 40 kg - controlado
• Flexiones: 3x8
Nota: si el jueves estas cansado, baja el volumen.

DÍA 2 - PIERNA (Martes)
• Sentadilla goblet: 3x10-12 @ 20 kg
• Circuito core (3 rondas, descanso 60s entre rondas):
  • Plancha: 30 segundos
  • Mountain climbers: 20 reps

DÍA 3 - TIRON (Jueves)
• Remo mancuerna: 4x8 @ 18 kg
"""


def test_extracts_requested_day_only_from_headers():
    section = _extract_day_section(ROUTINE, "jueves")

    assert section is not None
    assert "DÍA 3" in section
    assert "Remo mancuerna" in section
    assert "Press banca" not in section


def test_parse_normal_exercises_and_circuits():
    section = _extract_day_section(ROUTINE, "martes")
    exercises = _parse_session_exercises(section)

    names = [exercise["name"] for exercise in exercises]
    assert names == ["Sentadilla goblet", "Plancha", "Mountain climbers"]
    assert exercises[0]["target_sets"] == 3
    assert exercises[0]["reps_min"] == 10
    assert exercises[0]["reps_max"] == 12
    assert all(ex["name"].lower() != "circuito core" for ex in exercises)
    assert exercises[1]["is_circuit"] is True
    assert exercises[1]["target_sets"] == 3
    assert exercises[2]["circuit_position"] == 1


def test_parse_preserves_time_units_without_duplicate_seconds():
    exercises = _parse_session_exercises("DÍA 1 (Lunes)\n• Plancha: 3x30 seg")

    assert exercises == [
        {
            "name": "Plancha",
            "target_sets": 3,
            "target_reps": "30 seg",
            "reps_min": 30,
            "reps_max": 30,
            "note": "",
            "suggested_rest": 60,
            "suggested_weight": 0.0,
            "is_circuit": False,
            "circuit_rounds": 0,
            "circuit_rest": 0,
            "circuit_position": 0,
            "circuit_size": 0,
        }
    ]
