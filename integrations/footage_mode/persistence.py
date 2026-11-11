"""Transactional Footage-Mode 2.2 -> AFS integration persistence.

This first persistence slice imports immutable source snapshots and proposed
coverage decisions. It deliberately does not invent canonical character/shot
IDs or promote tool output to approval.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.models import (
    FMCoverageDecision,
    FMSourceRange,
    IntegrationObjectSnapshot,
    IntegrationRun,
    IntegrationSource,
)
from .adapter import FootageModeAdapter
from .schema_mapper import coverage_to_canonical, source_kind_from_scene
from .version_mapper import package_snapshot


class PersistenceImportError(ValueError):
    """Input, provenance, mapping, or idempotency conflict."""


def _canonical_json(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _sha256(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value)).hexdigest()


def _load_json_member(archive_path: str | Path, suffix: str) -> dict[str, Any]:
    import zipfile

    with zipfile.ZipFile(archive_path) as archive:
        matches = [name for name in archive.namelist() if name.endswith(suffix)]
        if len(matches) != 1:
            raise PersistenceImportError(f"expected exactly one archive member ending with {suffix!r}; found {len(matches)}")
        try:
            payload = json.loads(archive.read(matches[0]).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise PersistenceImportError(f"invalid JSON in {matches[0]}: {exc}") from exc
        if not isinstance(payload, dict):
            raise PersistenceImportError(f"{matches[0]} must contain a JSON object")
        return payload


def load_heaven_ship_81_documents(archive_path: str | Path) -> tuple[dict, dict]:
    """Load the two real 8.1 source documents from a verified FM archive."""
    adapter = FootageModeAdapter()
    adapter.inspect_source(archive_path)
    coverage = _load_json_member(archive_path, "heaven-ship-8.1-coverage-decisions.json")
    events = _load_json_member(archive_path, "heaven-ship-8.1-events.json")
    return coverage, events


def import_coverage_documents(
    db: Session,
    *,
    project_id: UUID,
    archive_path: str | Path,
    coverage_document: dict[str, Any],
    events_document: dict[str, Any],
    idempotency_key: str,
    source_code: str = "FOOTAGE_MODE_22B",
) -> UUID:
    """Persist one 8.1 integration run atomically; caller must provide a fresh Session.

    All event and decision payloads are retained verbatim in immutable snapshots.
    The event and shot source keys are not silently converted into AFS UUIDs.
    """
    if not isinstance(idempotency_key, str) or not idempotency_key.strip() or len(idempotency_key) > 160:
        raise PersistenceImportError("idempotency_key must be a non-empty string of at most 160 characters")
    if not isinstance(coverage_document, dict) or not isinstance(events_document, dict):
        raise PersistenceImportError("coverage_document and events_document must be JSON objects")

    adapter = FootageModeAdapter()
    descriptor = adapter.inspect_source(archive_path)
    coverage_scene = coverage_document.get("scene")
    events_scene = events_document.get("scene")
    source_kind = source_kind_from_scene(coverage_scene)
    if source_kind != source_kind_from_scene(events_scene):
        raise PersistenceImportError("event and coverage documents disagree on source provenance")
    if source_kind != "SOURCE_ACTING_TASK":
        raise PersistenceImportError("this import profile is explicitly for the Heaven Ship 8.1 ACTING TASK source")

    events = events_document.get("events")
    decisions = coverage_document.get("event_decisions")
    if not isinstance(events, list) or not isinstance(decisions, list):
        raise PersistenceImportError("events and event_decisions must be arrays")
    event_by_key: dict[str, dict] = {}
    for event in events:
        checked = adapter.validate_event(event, source_kind)
        key = checked.get("event_id")
        if not isinstance(key, str) or not key or key in event_by_key:
            raise PersistenceImportError("event_id must be unique, non-empty text")
        event_by_key[key] = event
    decision_by_key: dict[str, dict] = {}
    for decision in decisions:
        mapped = coverage_to_canonical(decision, source_kind)
        key = mapped["event_source_key"]
        if key in decision_by_key:
            raise PersistenceImportError(f"duplicate coverage decision for event {key}")
        if key not in event_by_key:
            raise PersistenceImportError(f"coverage decision references unknown event {key}")
        source = event_by_key[key].get("source") or {}
        source_range = decision.get("source_line_range")
        if source_range is not None:
            if source.get("line_start") != source_range[0] or source.get("line_end") != source_range[1]:
                raise PersistenceImportError(f"source line range mismatch for event {key}")
        decision_by_key[key] = decision
    if set(event_by_key) != set(decision_by_key):
        missing = sorted(set(event_by_key) - set(decision_by_key))
        extra = sorted(set(decision_by_key) - set(event_by_key))
        raise PersistenceImportError(f"event/decision key sets differ; missing decisions={missing}, extra decisions={extra}")

    input_snapshot = {
        "source_kind": source_kind,
        "scene": dict(coverage_scene),
        "coverage_schema_version": coverage_document.get("schema_version"),
        "events_schema_version": events_document.get("schema_version"),
        "engine_version": coverage_document.get("engine_version"),
        "optimization": coverage_document.get("optimization", {}),
        "selected_shots": coverage_document.get("selected_shots", []),
        "master_coverage_policy": coverage_document.get("master_coverage_policy", {}),
        "summary": coverage_document.get("summary", {}),
        "limits": coverage_document.get("limits", []),
        "coverage_document_metadata": {k: v for k, v in coverage_document.items() if k != "event_decisions"},
        "events_document_metadata": {k: v for k, v in events_document.items() if k != "events"},
        "event_order": [event["event_id"] for event in events],
        "decision_order": [decision["event_id"] for decision in decisions],
        "event_count": len(events),
        "decision_count": len(decisions),
        "events_document_sha256": _sha256(events_document),
        "coverage_document_sha256": _sha256(coverage_document),
    }

    # The entire operation is atomic. A failed FK, duplicate, or validation error
    # rolls back source/run/snapshots/ranges/decisions together.
    with db.begin():
        source = db.scalar(select(IntegrationSource).where(
            IntegrationSource.project_id == project_id,
            IntegrationSource.code == source_code,
        ))
        if source is None:
            source = IntegrationSource(
                project_id=project_id,
                code=source_code,
                source_kind="footage_mode",
                display_name="Footage-Mode 2.2-B recovered package",
                source_version=descriptor.version,
                source_sha256=descriptor.archive_sha256,
                config_snapshot=package_snapshot(descriptor),
            )
            db.add(source)
            db.flush()
        elif source.source_sha256 != descriptor.archive_sha256 or source.source_version != descriptor.version:
            raise PersistenceImportError("integration source code already points to a different immutable package")

        existing = db.scalar(select(IntegrationRun).where(
            IntegrationRun.integration_source_id == source.id,
            IntegrationRun.idempotency_key == idempotency_key,
        ))
        if existing is not None:
            if existing.input_snapshot != input_snapshot:
                raise PersistenceImportError("idempotency key was already used with different input")
            return existing.id

        run = IntegrationRun(
            project_id=project_id,
            integration_source_id=source.id,
            run_type="import",
            status="completed",
            idempotency_key=idempotency_key,
            package_version=descriptor.version,
            package_sha256=descriptor.archive_sha256,
            command_snapshot={"operation": "import_coverage_documents", "adapter": "AFS-FM-Persistence-1.0"},
            input_snapshot=input_snapshot,
            output_snapshot={
                "stage": "source_staging",
                "persisted_events": len(events),
                "persisted_decisions": len(decisions),
                "canonical_entities_created": False,
                "performance_tracks_imported": False,
            },
            validation_snapshot={
                "source_kind": source_kind,
                "event_decision_key_parity": True,
                "source_ranges_verified": True,
                "canonical_entity_resolution_complete": False,
                "performance_track_source_available": False,
                "human_approval": False,
            },
            exit_code=0,
            started_at=datetime.now(timezone.utc),
            finished_at=datetime.now(timezone.utc),
        )
        db.add(run)
        db.flush()

        for key, event in event_by_key.items():
            source_range = event.get("source") or {}
            db.add(IntegrationObjectSnapshot(
                project_id=project_id,
                integration_run_id=run.id,
                source_object_type="dramatic_event",
                source_object_key=key,
                raw_payload=event,
                raw_sha256=_sha256(event),
                source_range_snapshot={"source_kind": source_kind, "source": source_range},
            ))
            line_start, line_end = source_range.get("line_start"), source_range.get("line_end")
            db.add(FMSourceRange(
                project_id=project_id,
                integration_run_id=run.id,
                canonical_entity_id=None,
                source_kind=source_kind,
                source_object_key=key,
                line_start=line_start,
                line_end=line_end,
                exact_text=source_range.get("exact_text"),
                timing_source="unknown",
                range_snapshot={"source": source_range, "event_id": key},
            ))

        for key, decision in decision_by_key.items():
            mapped = coverage_to_canonical(decision, source_kind)
            db.add(IntegrationObjectSnapshot(
                project_id=project_id,
                integration_run_id=run.id,
                source_object_type="coverage_decision",
                source_object_key=key,
                raw_payload=decision,
                raw_sha256=_sha256(decision),
                source_range_snapshot=mapped["source_range_snapshot"],
            ))
            # selected_shot_source_keys remain source keys. No AFS entity IDs are
            # fabricated; they can be resolved later after an explicit mapping.
            db.add(FMCoverageDecision(
                project_id=project_id,
                integration_run_id=run.id,
                event_entity_id=None,
                event_source_key=key,
                coverage_status=mapped["coverage_status"],
                required_dimensions=mapped["required_dimensions"],
                covered_dimensions=mapped["covered_dimensions"],
                selected_shot_source_keys=mapped["selected_shot_source_keys"],
                selected_shot_entity_ids=[],
                source_range_snapshot=mapped["source_range_snapshot"],
                confidence=None,
                human_review_required=True,
                review_state="proposed",
                decision_snapshot=dict(decision),
            ))
        db.flush()
        return run.id


def export_run_bundle(db: Session, *, integration_run_id: UUID) -> dict[str, Any]:
    """Reconstruct the imported 8.1 bundle from persisted immutable records."""
    run = db.get(IntegrationRun, integration_run_id)
    if run is None:
        raise PersistenceImportError("integration run not found")
    snapshots = db.scalars(select(IntegrationObjectSnapshot).where(
        IntegrationObjectSnapshot.integration_run_id == integration_run_id
    )).all()
    for row in snapshots:
        if _sha256(row.raw_payload) != row.raw_sha256:
            raise PersistenceImportError(f"snapshot integrity check failed for {row.source_object_type}:{row.source_object_key}")
    events = {row.source_object_key: row.raw_payload for row in snapshots if row.source_object_type == "dramatic_event"}
    decisions = {row.source_object_key: row.raw_payload for row in snapshots if row.source_object_type == "coverage_decision"}
    if set(events) != set(decisions):
        raise PersistenceImportError("persisted event and coverage snapshots are incomplete or inconsistent")
    meta = run.input_snapshot
    event_order = meta.get("event_order", sorted(events))
    decision_order = meta.get("decision_order", sorted(decisions))
    if set(event_order) != set(events) or set(decision_order) != set(decisions):
        raise PersistenceImportError("persisted source ordering metadata does not match snapshot keys")
    ordered_events = [events[key] for key in event_order]
    ordered_decisions = [decisions[key] for key in decision_order]
    coverage_document = dict(meta["coverage_document_metadata"])
    coverage_document["event_decisions"] = ordered_decisions
    events_document = dict(meta["events_document_metadata"])
    events_document["events"] = ordered_events
    # Canonical mapping is maintained separately from immutable source proposals.
    # Export the current resolution view without rewriting the original JSON.
    from .mapping_service import _resolve_required, MappingResolutionError
    source = db.get(IntegrationSource, run.integration_source_id)
    canonical_links = {"status": "unresolved", "events": {}, "shots": {}}
    if source is not None:
        event_keys = [item["event_id"] for item in ordered_decisions]
        shot_keys = [key for item in ordered_decisions for key in item.get("selected_shot_ids", [])]
        try:
            event_map = _resolve_required(db, source=source, source_object_type="dramatic_event", source_keys=event_keys)
            shot_map = _resolve_required(db, source=source, source_object_type="shot", source_keys=shot_keys)
            canonical_links = {
                "status": "complete",
                "events": {key: str(value) for key, value in event_map.items()},
                "shots": {key: str(value) for key, value in shot_map.items()},
            }
        except MappingResolutionError as exc:
            canonical_links = {"status": "incomplete", "events": {}, "shots": {}, "reason": str(exc)}
    return {
        "scene": meta["scene"],
        "events": ordered_events,
        "event_decisions": ordered_decisions,
        "coverage_document": coverage_document,
        "events_document": events_document,
        "canonical_links": canonical_links,
        "run": {
            "id": str(run.id),
            "package_version": run.package_version,
            "package_sha256": run.package_sha256,
            "source_kind": meta["source_kind"],
            "event_count": len(events),
            "decision_count": len(decisions),
            "human_approval": False,
            "stage": run.output_snapshot.get("stage", "unknown") if run.output_snapshot else "unknown",
        },
    }
