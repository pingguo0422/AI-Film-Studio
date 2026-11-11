"""Deterministic, provider-neutral specialist capability discovery and selection."""
from __future__ import annotations
from dataclasses import dataclass
from typing import Any
from sqlalchemy import select
from sqlalchemy.orm import Session
from backend.app.models import Agent, AgentVersion, AgentSkillBinding, Skill, SkillVersion


class CapabilityResolutionError(ValueError):
    pass


@dataclass(frozen=True)
class CapabilityQuery:
    capability: str
    required_tags: tuple[str, ...] = ()
    modality: str | None = None
    language: str | None = None
    task_type: str | None = None
    excluded_agent_codes: tuple[str, ...] = ()


def _tokens(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    values = [value] if isinstance(value, str) else value
    if not isinstance(values, (list, tuple, set)):
        return ()
    return tuple(sorted({str(v).strip().casefold() for v in values if str(v).strip()}))


def active_capability_catalog(db: Session) -> list[dict]:
    rows = db.execute(
        select(Agent, AgentVersion, Skill, SkillVersion)
        .join(AgentVersion, AgentVersion.agent_id == Agent.id)
        .join(AgentSkillBinding, AgentSkillBinding.agent_version_id == AgentVersion.id)
        .join(SkillVersion, SkillVersion.id == AgentSkillBinding.skill_version_id)
        .join(Skill, Skill.id == SkillVersion.skill_id)
        .where(Agent.lifecycle_state == "active", Skill.lifecycle_state == "active")
        .order_by(Agent.code, AgentVersion.version_number, Skill.code, SkillVersion.version_number)
    ).all()
    catalog = []
    for agent, agent_version, skill, skill_version in rows:
        agent_def = agent_version.definition_snapshot if isinstance(agent_version.definition_snapshot, dict) else {}
        skill_def = skill_version.definition_snapshot if isinstance(skill_version.definition_snapshot, dict) else {}
        profile = agent_def.get("profile", {}) if isinstance(agent_def.get("profile", {}), dict) else {}
        capabilities = _tokens(skill_def.get("capabilities", []))
        if not capabilities:
            capabilities = _tokens(profile.get("capabilities", []))
        catalog.append({
            "agent_id": str(agent.id), "agent_code": agent.code, "agent_name": agent.display_name,
            "agent_version_id": str(agent_version.id), "agent_version": agent_version.version_number,
            "agent_version_sha256": agent_version.definition_sha256,
            "skill_id": str(skill.id), "skill_code": skill.code, "skill_name": skill.display_name,
            "skill_version_id": str(skill_version.id), "skill_version": skill_version.version_number,
            "skill_version_sha256": skill_version.definition_sha256,
            "capabilities": capabilities,
            "specialties": _tokens(profile.get("specialties", [])),
            "tags": _tokens(profile.get("tags", [])),
            "modalities": _tokens(profile.get("modalities", [])),
            "languages": _tokens(profile.get("languages", [])),
            "task_types": _tokens(profile.get("task_types", [])),
            "quality_rubric": profile.get("quality_rubric", {}),
        })
    return catalog


def resolve_specialist(catalog: list[dict], query: CapabilityQuery) -> dict:
    if not isinstance(query.capability, str) or not query.capability.strip():
        raise CapabilityResolutionError("capability must be a non-empty string")
    capability = query.capability.strip().casefold()
    for label, value in (("modality", query.modality), ("language", query.language), ("task_type", query.task_type)):
        if value is not None and (not isinstance(value, str) or not value.strip()):
            raise CapabilityResolutionError(f"{label} must be a non-empty string when provided")
    required_tags = set(_tokens(query.required_tags))
    excluded = set(_tokens(query.excluded_agent_codes))
    candidates = []
    for item in catalog:
        if capability not in item.get("capabilities", ()) or item.get("agent_code", "").casefold() in excluded:
            continue
        if not required_tags.issubset(set(item.get("tags", ())) | set(item.get("specialties", ()))):
            continue
        if query.modality and query.modality.casefold() not in item.get("modalities", ()):
            continue
        if query.language and query.language.casefold() not in item.get("languages", ()):
            continue
        if query.task_type and item.get("task_types") and query.task_type.casefold() not in item["task_types"]:
            continue
        candidates.append(item)
    if not candidates:
        raise CapabilityResolutionError(f"no active specialist matches capability '{capability}' and requested constraints")
    # Exact constrained matches only. Do not silently pick a specialist by row order.
    identities = {(x["agent_version_id"], x["skill_version_id"]) for x in candidates}
    if len(identities) != 1:
        choices = ", ".join(f"{x['agent_code']}:{x['skill_code']}" for x in candidates)
        raise CapabilityResolutionError(f"capability '{capability}' must resolve to exactly one specialist; ambiguous matches ({choices}); constrain the request further")
    return candidates[0]
