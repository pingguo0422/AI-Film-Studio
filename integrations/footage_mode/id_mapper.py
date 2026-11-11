"""Stable source-key mapping helpers. Database mapping rows are authoritative."""
from sqlalchemy import select
from sqlalchemy.orm import Session
from backend.app.models import IntegrationObjectMapping

def find_mapping(db: Session, *, integration_source_id, source_object_type: str, source_object_key: str):
    return db.scalar(select(IntegrationObjectMapping).where(
        IntegrationObjectMapping.integration_source_id == integration_source_id,
        IntegrationObjectMapping.source_object_type == source_object_type,
        IntegrationObjectMapping.source_object_key == source_object_key,
    ))

class MappingResolutionError(Exception):
    pass

def resolve_source_keys(db: Session, *, integration_source_id, source_object_type: str, source_keys: list[str]) -> list:
    """Resolve every source key or fail closed; never mint guessed canonical IDs."""
    if not isinstance(source_keys, list) or any(not isinstance(x, str) for x in source_keys):
        raise MappingResolutionError("source keys must be a list of strings")
    if not source_keys:
        return []
    rows = db.scalars(select(IntegrationObjectMapping).where(
        IntegrationObjectMapping.integration_source_id == integration_source_id,
        IntegrationObjectMapping.source_object_type == source_object_type,
        IntegrationObjectMapping.source_object_key.in_(source_keys),
        IntegrationObjectMapping.mapping_state == "mapped",
    )).all()
    resolved = {row.source_object_key: row.canonical_entity_id for row in rows}
    missing = [key for key in source_keys if key not in resolved]
    if missing:
        raise MappingResolutionError(f"unmapped source keys: {', '.join(missing)}")
    return [resolved[key] for key in source_keys]
