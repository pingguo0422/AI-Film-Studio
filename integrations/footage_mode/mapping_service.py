"""Explicit, fail-closed mapping from Footage-Mode source keys to AFS entities.

Mappings are never inferred from display names. A caller must supply an existing
canonical entity UUID and a human-readable mapping rationale.
"""
from __future__ import annotations

from datetime import datetime, timezone
from contextlib import contextmanager
from typing import Iterable
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.models import (
    Entity,
    FMCoverageDecision,
    IntegrationObjectMapping,
    IntegrationRun,
    IntegrationSource,
)


class MappingResolutionError(ValueError):
    """A source object cannot be safely resolved to one canonical entity."""


@contextmanager
def _atomic_scope(db: Session):
    """Use a savepoint when the caller already owns a Session transaction."""
    with (db.begin_nested() if db.in_transaction() else db.begin()):
        yield


_ALLOWED_SOURCE_TYPES = {
    "dramatic_event": "dramatic_event",
    "shot": "shot",
    "character": "character",
}


def register_source_mapping(
    db: Session,
    *,
    integration_source_id: UUID,
    source_object_type: str,
    source_object_key: str,
    canonical_entity_id: UUID,
    mapping_rationale: str,
    actor_principal_id: UUID | None = None,
) -> UUID:
    """Create an explicit source-key mapping; same mapping is idempotent.

    Re-pointing an already mapped source key is intentionally rejected. A future
    governed remapping workflow must preserve mapping history rather than mutate it.
    """
    expected_entity_type = _ALLOWED_SOURCE_TYPES.get(source_object_type)
    if expected_entity_type is None:
        raise MappingResolutionError(f"unsupported source_object_type: {source_object_type!r}")
    if not isinstance(source_object_key, str) or not source_object_key.strip() or len(source_object_key) > 256:
        raise MappingResolutionError("source_object_key must be non-empty text up to 256 characters")
    if not isinstance(mapping_rationale, str) or not mapping_rationale.strip():
        raise MappingResolutionError("mapping_rationale is required; name matching is not sufficient evidence")

    with _atomic_scope(db):
        source = db.get(IntegrationSource, integration_source_id)
        if source is None:
            raise MappingResolutionError("integration source does not exist")
        entity = db.get(Entity, canonical_entity_id)
        if entity is None:
            raise MappingResolutionError("canonical entity does not exist")
        if entity.project_id != source.project_id:
            raise MappingResolutionError("canonical entity belongs to a different project")
        if entity.entity_type != expected_entity_type:
            raise MappingResolutionError(
                f"source type {source_object_type!r} requires canonical entity_type {expected_entity_type!r}; "
                f"got {entity.entity_type!r}"
            )

        row = db.scalar(select(IntegrationObjectMapping).where(
            IntegrationObjectMapping.integration_source_id == integration_source_id,
            IntegrationObjectMapping.source_object_type == source_object_type,
            IntegrationObjectMapping.source_object_key == source_object_key,
        ))
        snapshot = {
            "mapping_rationale": mapping_rationale.strip(),
            "actor_principal_id": str(actor_principal_id) if actor_principal_id else None,
            "mapped_at": datetime.now(timezone.utc).isoformat(),
            "mapping_method": "explicit_canonical_uuid",
        }
        if row is not None:
            if row.mapping_state == "mapped" and row.canonical_entity_id == canonical_entity_id:
                return row.id
            if row.mapping_state == "mapped":
                raise MappingResolutionError("source key is already mapped to a different canonical entity")
            if row.mapping_state == "retired":
                raise MappingResolutionError("retired source mapping cannot be reactivated")
            row.canonical_entity_id = canonical_entity_id
            row.mapping_state = "mapped"
            row.mapping_snapshot = {**(row.mapping_snapshot or {}), **snapshot}
            db.flush()
            return row.id

        row = IntegrationObjectMapping(
            project_id=source.project_id,
            integration_source_id=source.id,
            source_object_type=source_object_type,
            source_object_key=source_object_key,
            canonical_entity_id=canonical_entity_id,
            mapping_state="mapped",
            mapping_snapshot=snapshot,
        )
        db.add(row)
        db.flush()
        return row.id


def _resolve_required(
    db: Session,
    *,
    source: IntegrationSource,
    source_object_type: str,
    source_keys: Iterable[str],
) -> dict[str, UUID]:
    keys = list(dict.fromkeys(source_keys))
    if not keys:
        return {}
    rows = db.scalars(select(IntegrationObjectMapping).where(
        IntegrationObjectMapping.integration_source_id == source.id,
        IntegrationObjectMapping.source_object_type == source_object_type,
        IntegrationObjectMapping.source_object_key.in_(keys),
        IntegrationObjectMapping.mapping_state == "mapped",
    )).all()
    by_key = {row.source_object_key: row for row in rows}
    missing = [key for key in keys if key not in by_key]
    if missing:
        raise MappingResolutionError(f"unmapped {source_object_type} source keys: {', '.join(missing)}")
    result: dict[str, UUID] = {}
    expected_type = _ALLOWED_SOURCE_TYPES[source_object_type]
    for key, row in by_key.items():
        entity = db.get(Entity, row.canonical_entity_id)
        if entity is None or entity.project_id != source.project_id or entity.entity_type != expected_type:
            raise MappingResolutionError(f"canonical mapping for {source_object_type}:{key} is invalid")
        result[key] = row.canonical_entity_id
    return result


def resolve_run_coverage_links(db: Session, *, integration_run_id: UUID) -> dict:
    """Resolve all event and selected-shot links in one transaction or do nothing."""
    with _atomic_scope(db):
        run = db.get(IntegrationRun, integration_run_id)
        if run is None:
            raise MappingResolutionError("integration run does not exist")
        source = db.get(IntegrationSource, run.integration_source_id)
        if source is None or source.project_id != run.project_id:
            raise MappingResolutionError("integration run source/project relationship is invalid")
        decisions = db.scalars(select(FMCoverageDecision).where(
            FMCoverageDecision.integration_run_id == run.id,
            FMCoverageDecision.project_id == run.project_id,
        ).order_by(FMCoverageDecision.event_source_key)).all()
        if not decisions:
            raise MappingResolutionError("integration run has no coverage decisions")

        event_keys = [row.event_source_key for row in decisions]
        shot_keys = [key for row in decisions for key in (row.selected_shot_source_keys or [])]
        event_map = _resolve_required(db, source=source, source_object_type="dramatic_event", source_keys=event_keys)
        shot_map = _resolve_required(db, source=source, source_object_type="shot", source_keys=shot_keys)

        # FMCoverageDecision is an immutable proposal. Canonical links live in
        # IntegrationObjectMapping and the run's derived output summary; never
        # mutate the original decision record after import.
        validation = dict(run.validation_snapshot or {})
        validation.update({
            "canonical_entity_resolution_complete": True,
            "canonical_event_mapping_count": len(event_map),
            "canonical_shot_mapping_count": len(shot_map),
            "human_approval": False,
        })
        run.validation_snapshot = validation
        output = dict(run.output_snapshot or {})
        output.update({
            "canonical_event_mappings": len(event_map),
            "canonical_shot_mappings": len(shot_map),
            "canonical_links_resolved": True,
            "canonical_event_entity_ids": {key: str(value) for key, value in event_map.items()},
            "canonical_shot_entity_ids": {key: str(value) for key, value in shot_map.items()},
        })
        run.output_snapshot = output
        db.flush()
        return {
            "integration_run_id": str(run.id),
            "event_mappings": len(event_map),
            "shot_mappings": len(shot_map),
            "decisions_verified": len(decisions),
            "proposal_records_mutated": 0,
            "human_approval": False,
        }
