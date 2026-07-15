from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from app.models import SuggestedAction
from app.settings import get_settings


class SkillNotFoundError(KeyError):
    pass


def load_skill(skill_id: str) -> dict[str, Any]:
    root = get_settings().workflow_skills_dir
    path = root / skill_id / "workflow.yaml"
    if not path.exists():
        raise SkillNotFoundError(f"Workflow skill not found: {skill_id}")
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def list_skills() -> list[dict[str, Any]]:
    root = get_settings().workflow_skills_dir
    skills = []
    for path in sorted(root.glob("*/workflow.yaml")):
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        skills.append({"id": data["id"], "name": data.get("name", data["id"]), "description": data.get("description", "")})
    return skills


def suggested_actions(skill: dict[str, Any]) -> list[SuggestedAction]:
    return [SuggestedAction.model_validate(item) for item in skill.get("suggested_next_actions", [])]
