from __future__ import annotations

from typing import Any

from app import db
from app.models import AgentResponse, FindingCard, Investigation, ToolCallTrace
from app.settings import get_settings
from app.workflows.loader import load_skill, suggested_actions
from app.workflows.tools import REGISTRY


class WorkflowContextError(ValueError):
    pass


def run_skill(skill_id: str, investigation: Investigation, parameters: dict[str, Any] | None = None) -> AgentResponse:
    parameters = parameters or {}
    skill = load_skill(skill_id)
    _validate_required_context(skill, investigation, parameters)
    initial_investigation = investigation.model_dump(mode="json")

    ctx: dict[str, Any] = {}
    trace: list[ToolCallTrace] = []
    created_cards: list[FindingCard] = []

    for step in skill.get("steps", []):
        step_id = step["id"]
        tool_name = step["tool"]
        tool = REGISTRY[tool_name]
        inputs = dict(step)
        inputs.update(parameters)
        inputs["skill_id"] = skill_id
        try:
            output = tool(investigation, inputs, ctx)
            ctx[step_id] = output
            if "card" in output:
                card = FindingCard.model_validate(output["card"])
                created_cards.append(card)
            trace.append(
                ToolCallTrace(
                    step_id=step_id,
                    tool=tool_name,
                    status="ok",
                    output_preview=_preview(output),
                )
            )
        except Exception as exc:  # noqa: BLE001 - returned to trace for demo transparency
            trace.append(ToolCallTrace(step_id=step_id, tool=tool_name, status="error", message=str(exc)))
            if isinstance(exc, ValueError):
                raise WorkflowContextError(str(exc)) from exc
            raise

    if created_cards:
        created_cards = db.save_finding_cards(get_settings().db_path, created_cards)
    if investigation.model_dump(mode="json") != initial_investigation:
        db.save_investigation(get_settings().db_path, investigation)

    actions = suggested_actions(skill)
    answer = _answer(skill, created_cards, ctx)
    return AgentResponse(
        answer=answer,
        selected_skill_id=skill_id,
        finding_cards=created_cards,
        suggested_actions=actions,
        trace=trace,
    )


def _validate_required_context(skill: dict[str, Any], inv: Investigation, params: dict[str, Any]) -> None:
    required = skill.get("required_context", [])
    missing = []
    for item in required:
        if item == "selected_cluster" and not (params.get("cluster_id") or inv.selected_cluster_id):
            missing.append("selected_cluster")
        if item == "pinned_finding":
            # The report route performs strict validation; workflow runner allows the skill to be selected.
            continue
    if missing:
        raise WorkflowContextError(
            "Missing required context: " + ", ".join(missing) + ". Select a burn cluster first."
        )


def _preview(output: dict[str, Any]) -> dict[str, Any]:
    preview = {}
    for k, v in output.items():
        if k == "card":
            preview["card_title"] = v.get("title")
        elif isinstance(v, (str, int, float, bool)) or v is None:
            preview[k] = v
        elif isinstance(v, list):
            preview[k] = f"list[{len(v)}]"
        elif isinstance(v, dict):
            preview[k] = f"dict[{len(v)}]"
    return preview


def _answer(skill: dict[str, Any], cards: list[FindingCard], ctx: dict[str, Any]) -> str:
    if skill.get("id") == "burned_area_accounting" and isinstance(ctx.get("annual"), dict):
        annual = ctx["annual"]
        by_year = annual.get("annual_by_year") or {}
        if by_year:
            parts = []
            for year, values in sorted(by_year.items()):
                completeness = "" if values.get("complete_year") else f" ({values.get('months_ingested', 0)}/12 months ingested)"
                parts.append(f"{year}: {float(values.get('burned_area_ha', 0.0)):,.1f} ha{completeness}")
            return "Real CLMS BA300 burned-area totals for Greece: " + "; ".join(parts) + ". No synthetic values were used."
    if not cards:
        return skill.get("completion_message", "Workflow completed.")
    titles = ", ".join(card.title for card in cards)
    return f"Completed **{skill.get('name', skill['id'])}** and saved finding: {titles}."
