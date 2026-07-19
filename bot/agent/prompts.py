from pathlib import Path


PROMPT_DIR = Path(__file__).with_name("prompts")
BASE_PROMPT_FILES = ("identity.md", "scope.md", "safety.md")
TASK_PROMPT_FILES = (
    "conversation.md",
    "routine_generation.md",
    "session_adjustment.md",
    "progression_explanation.md",
)
PROMPT_VERSION = "2026-07-19"


def load_prompt(name: str) -> str:
    return (PROMPT_DIR / name).read_text(encoding="utf-8").strip()


def build_system_prompt(context: dict) -> str:
    parts = [load_prompt(name) for name in BASE_PROMPT_FILES + TASK_PROMPT_FILES]
    return "\n\n".join(parts).format(**context)
