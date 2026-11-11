from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, event, select, func
from sqlalchemy.orm import Session

from backend.app.db.base import Base
from backend.app.db.ids import uuid7
from backend.app.models import (
    Entity, FMCoverageDecision, IntegrationObjectMapping,
    IntegrationRun, IntegrationSource, Project,
)
from integrations.footage_mode.mapping_service import (
    MappingResolutionError, register_source_mapping, resolve_run_coverage_links,
)
from integrations.footage_mode.persistence import (
    export_run_bundle, import_coverage_documents, load_heaven_ship_81_documents,
)

ROOT = Path(__file__).resolve().parents[1]
ARCHIVE = ROOT / "source-baseline" / "Footage-Mode-2.2-B.zip"


@pytest.fixture
def imported_run():
    engine = create_engine("sqlite+pysqlite:///:memory:")

    @event.listens_for(engine, "connect")
    def enable_fk(connection, _):
        connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as db:
        project = Project(id=uuid7(), code="PRJ_MAP", name="天堂号映射测试")
        db.add(project)
        db.commit()
        coverage, events = load_heaven_ship_81_documents(ARCHIVE)
        run_id = import_coverage_documents(
            db, project_id=project.id, archive_path=ARCHIVE,
            coverage_document=coverage, events_document=events,
            idempotency_key="mapping-service-fixture",
        )
        run = db.get(IntegrationRun, run_id)
        source = db.get(IntegrationSource, run.integration_source_id)
        db.commit()
        yield db, project.id, source.id, run_id, coverage
    engine.dispose()


def test_explicit_mapping_is_idempotent_and_rejects_repoint(imported_run):
    db, project_id, source_id, _run_id, _coverage = imported_run
    entity = Entity(id=uuid7(), project_id=project_id, entity_type="dramatic_event", title="事件实体")
    other = Entity(id=uuid7(), project_id=project_id, entity_type="dramatic_event", title="另一个事件")
    db.add_all([entity, other])
    db.commit()
    kwargs = dict(
        integration_source_id=source_id, source_object_type="dramatic_event",
        source_object_key="EVT-001", canonical_entity_id=entity.id,
        mapping_rationale="经导演审阅的事件 ID 对照表明确指向该实体",
    )
    first = register_source_mapping(db, **kwargs)
    db.commit()
    second = register_source_mapping(db, **kwargs)
    db.commit()
    assert first == second
    with pytest.raises(MappingResolutionError, match="already mapped"):
        register_source_mapping(db, **{**kwargs, "canonical_entity_id": other.id})
    assert db.scalar(select(func.count()).select_from(IntegrationObjectMapping)) == 1


def test_mapping_rejects_cross_project_and_wrong_entity_type(imported_run):
    db, project_id, source_id, _run_id, _coverage = imported_run
    wrong_project = Project(id=uuid7(), code="PRJ_OTHER", name="其他项目")
    db.add(wrong_project)
    db.flush()
    foreign_entity = Entity(id=uuid7(), project_id=wrong_project.id, entity_type="dramatic_event", title="外项目事件")
    wrong_type = Entity(id=uuid7(), project_id=project_id, entity_type="character", title="人物")
    db.add_all([foreign_entity, wrong_type])
    db.commit()
    base = dict(integration_source_id=source_id, source_object_type="dramatic_event", source_object_key="EVT-X", mapping_rationale="有依据的显式映射")
    with pytest.raises(MappingResolutionError, match="different project"):
        register_source_mapping(db, **base, canonical_entity_id=foreign_entity.id)
    with pytest.raises(MappingResolutionError, match="requires canonical entity_type"):
        register_source_mapping(db, **base, canonical_entity_id=wrong_type.id)


def test_run_resolution_fails_closed_without_partial_decision_mutation(imported_run):
    db, project_id, source_id, run_id, coverage = imported_run
    first_decision = coverage["event_decisions"][0]
    event_entity = Entity(id=uuid7(), project_id=project_id, entity_type="dramatic_event", title="事件")
    db.add(event_entity)
    db.commit()
    register_source_mapping(
        db, integration_source_id=source_id, source_object_type="dramatic_event",
        source_object_key=first_decision["event_id"], canonical_entity_id=event_entity.id,
        mapping_rationale="测试用明确映射",
    )
    db.commit()
    with pytest.raises(MappingResolutionError, match="unmapped dramatic_event"):
        resolve_run_coverage_links(db, integration_run_id=run_id)
    db.rollback()
    decision = db.scalar(select(FMCoverageDecision).where(FMCoverageDecision.integration_run_id == run_id))
    assert decision.event_entity_id is None
    assert decision.selected_shot_entity_ids == []
    run = db.get(IntegrationRun, run_id)
    assert run.validation_snapshot["canonical_entity_resolution_complete"] is False


def test_complete_mapping_resolution_is_separate_from_immutable_proposal(imported_run):
    db, project_id, source_id, run_id, coverage = imported_run
    event_keys = [item["event_id"] for item in coverage["event_decisions"]]
    shot_keys = list(dict.fromkeys(key for item in coverage["event_decisions"] for key in item["selected_shot_ids"]))
    entities = []
    for key in event_keys:
        entity = Entity(id=uuid7(), project_id=project_id, entity_type="dramatic_event", title=f"事件 {key}")
        db.add(entity)
        entities.append(("dramatic_event", key, entity))
    for key in shot_keys:
        entity = Entity(id=uuid7(), project_id=project_id, entity_type="shot", title=f"镜头 {key}")
        db.add(entity)
        entities.append(("shot", key, entity))
    db.commit()
    for source_type, key, entity in entities:
        register_source_mapping(
            db, integration_source_id=source_id, source_object_type=source_type,
            source_object_key=key, canonical_entity_id=entity.id,
            mapping_rationale="《天堂号》8.1 经人工核对的 source-key / AFS UUID 映射清单",
        )
    db.commit()

    before = db.scalars(select(FMCoverageDecision).where(FMCoverageDecision.integration_run_id == run_id)).all()
    before_ids = {row.event_source_key: (row.event_entity_id, list(row.selected_shot_entity_ids)) for row in before}
    result = resolve_run_coverage_links(db, integration_run_id=run_id)
    db.commit()
    assert result["event_mappings"] == 52
    assert result["shot_mappings"] == len(shot_keys)
    assert result["proposal_records_mutated"] == 0
    run = db.get(IntegrationRun, run_id)
    assert run.validation_snapshot["canonical_entity_resolution_complete"] is True
    after = db.scalars(select(FMCoverageDecision).where(FMCoverageDecision.integration_run_id == run_id)).all()
    assert {row.event_source_key: (row.event_entity_id, list(row.selected_shot_entity_ids)) for row in after} == before_ids
    exported = export_run_bundle(db, integration_run_id=run_id)
    assert exported["canonical_links"]["status"] == "complete"
    assert len(exported["canonical_links"]["events"]) == 52
    assert len(exported["canonical_links"]["shots"]) == len(shot_keys)
    assert exported["run"]["human_approval"] is False
