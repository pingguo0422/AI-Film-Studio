"""Canonical mapping helpers; preserve Footage-Mode source fields verbatim."""
from .adapter import FootageModeAdapter

_adapter = FootageModeAdapter()

def event_to_canonical(event: dict, source_kind: str) -> dict:
    return _adapter.validate_event(event, source_kind)

def source_kind_from_scene(scene: dict) -> str:
    """Translate explicit source_type metadata; never guess screenplay provenance."""
    if not isinstance(scene, dict):
        raise ValueError("scene metadata must be an object")
    mapping = {
        "acting_task": "SOURCE_ACTING_TASK",
        "screenplay": "SOURCE_SCREENPLAY",
        "scene_json": "SOURCE_SCENE_JSON",
        "events_json": "SOURCE_EVENTS_JSON",
        "shots_json": "SOURCE_SHOTS_JSON",
    }
    try:
        return mapping[scene.get("source_type")]
    except KeyError as exc:
        raise ValueError("scene.source_type is missing or unsupported; source provenance cannot be guessed") from exc

def coverage_to_canonical(decision: dict, source_kind: str) -> dict:
    """Validate and map a 2.2 event_decisions record without inventing AFS IDs."""
    if source_kind not in {"SOURCE_ACTING_TASK", "SOURCE_SCREENPLAY", "SOURCE_SCENE_JSON", "SOURCE_EVENTS_JSON", "SOURCE_SHOTS_JSON"}:
        raise ValueError("unsupported explicit source provenance")
    checked = _adapter.validate_coverage_decision(decision)
    source_key = checked.get("event_id") or checked.get("event_source_key")
    if not isinstance(source_key, str) or not source_key:
        raise ValueError("coverage decision must contain a stable event source key")
    source_range = checked.get("source_line_range")
    if source_range is not None and (
        not isinstance(source_range, list) or len(source_range) != 2 or
        any(type(x) is not int for x in source_range) or source_range[0] <= 0 or source_range[1] < source_range[0]
    ):
        raise ValueError("source_line_range must be a valid two-integer inclusive range")
    selected = checked.get("selected_shot_ids", [])
    if not isinstance(selected, list) or any(not isinstance(x, str) for x in selected):
        raise ValueError("selected_shot_ids must be a list of source shot keys")
    return {
        "event_source_key": source_key,
        "coverage_status": checked["coverage_status"],
        "required_dimensions": list(checked["required_dimensions"]),
        "covered_dimensions": list(checked["covered_dimensions"]),
        "selected_shot_source_keys": list(selected),
        # Resolve these through integration_object_mappings before storing any AFS entity IDs.
        "selected_shot_entity_ids": [],
        "source_range_snapshot": {"source_kind": source_kind, "source_line_range": source_range} if source_range else {"source_kind": source_kind},
        "human_review_required": True,
        "review_state": "proposed",
        "decision_snapshot": dict(decision),
    }

def performance_track_to_canonical(track: dict) -> dict:
    return _adapter.validate_track(track)
