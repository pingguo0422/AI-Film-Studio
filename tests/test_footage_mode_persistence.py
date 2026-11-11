import zipfile
from pathlib import Path

import pytest
from sqlalchemy import create_engine, event, select, func
from sqlalchemy.orm import Session

from backend.app.db.base import Base
from backend.app.db.ids import uuid7
from backend.app.models import (
    FMCoverageDecision, FMSourceRange, IntegrationObjectSnapshot,
    IntegrationRun, IntegrationSource, Project,
)
from integrations.footage_mode.persistence import (
    PersistenceImportError,
    export_run_bundle,
    import_coverage_documents,
    load_heaven_ship_81_documents,
)

ROOT = Path(__file__).resolve().parents[1]
ARCHIVE = ROOT / "source-baseline" / "Footage-Mode-2.2-B.zip"


@pytest.fixture
def db_session():
    engine = create_engine("sqlite+pysqlite:///:memory:")

    @event.listens_for(engine, "connect")
    def enable_fk(connection, _):
        connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as db:
        project = Project(id=uuid7(), code="PRJ_HEAVEN", name="天堂号")
        db.add(project)
        db.commit()
        yield db, project.id
    engine.dispose()


def test_real_81_documents_import_transactionally_and_export_roundtrip(db_session):
    db, project_id = db_session
    coverage, events = load_heaven_ship_81_documents(ARCHIVE)
    run_id = import_coverage_documents(
        db, project_id=project_id, archive_path=ARCHIVE,
        coverage_document=coverage, events_document=events,
        idempotency_key="heaven-ship-S08-coverage-import-01",
    )

    run = db.get(IntegrationRun, run_id)
    assert run.status == "completed"
    assert run.input_snapshot["source_kind"] == "SOURCE_ACTING_TASK"
    assert run.input_snapshot["event_count"] == 52
    assert run.output_snapshot["stage"] == "source_staging"
    assert run.validation_snapshot["canonical_entity_resolution_complete"] is False
    assert run.validation_snapshot["performance_track_source_available"] is False
    assert db.scalar(select(func.count()).select_from(IntegrationObjectSnapshot).where(IntegrationObjectSnapshot.integration_run_id == run_id)) == 104
    assert db.scalar(select(func.count()).select_from(FMSourceRange).where(FMSourceRange.integration_run_id == run_id)) == 52
    assert db.scalar(select(func.count()).select_from(FMCoverageDecision).where(FMCoverageDecision.integration_run_id == run_id)) == 52
    assert db.scalar(select(func.count()).select_from(IntegrationSource).where(IntegrationSource.project_id == project_id)) == 1

    decisions = db.scalars(select(FMCoverageDecision).where(FMCoverageDecision.integration_run_id == run_id)).all()
    assert sum(row.coverage_status == "covered" for row in decisions) == 5
    assert sum(row.coverage_status == "partially_covered" for row in decisions) == 16
    assert sum(row.coverage_status == "not_selected" for row in decisions) == 31
    assert all(row.event_entity_id is None for row in decisions)
    assert all(row.selected_shot_entity_ids == [] for row in decisions)
    assert all(row.human_review_required and row.review_state == "proposed" for row in decisions)

    exported = export_run_bundle(db, integration_run_id=run_id)
    assert exported["scene"] == coverage["scene"]
    assert exported["events"] == events["events"]
    assert exported["event_decisions"] == coverage["event_decisions"]
    assert exported["coverage_document"] == coverage
    assert exported["events_document"] == events
    assert exported["run"]["human_approval"] is False


def test_import_is_idempotent_for_same_key_and_input(db_session):
    db, project_id = db_session
    coverage, events = load_heaven_ship_81_documents(ARCHIVE)
    kwargs = dict(project_id=project_id, archive_path=ARCHIVE,
                  coverage_document=coverage, events_document=events,
                  idempotency_key="same-request")
    first = import_coverage_documents(db, **kwargs)
    second = import_coverage_documents(db, **kwargs)
    assert first == second
    assert db.scalar(select(func.count()).select_from(IntegrationRun)) == 1


def test_import_rejects_mismatched_source_ranges_without_partial_writes(db_session):
    db, project_id = db_session
    coverage, events = load_heaven_ship_81_documents(ARCHIVE)
    coverage["event_decisions"][0]["source_line_range"] = [99, 99]
    with pytest.raises(PersistenceImportError, match="source line range mismatch"):
        import_coverage_documents(
            db, project_id=project_id, archive_path=ARCHIVE,
            coverage_document=coverage, events_document=events,
            idempotency_key="bad-source-range",
        )
    assert db.scalar(select(func.count()).select_from(IntegrationSource)) == 0
    assert db.scalar(select(func.count()).select_from(IntegrationRun)) == 0
    assert db.scalar(select(func.count()).select_from(IntegrationObjectSnapshot)) == 0


def test_idempotency_key_cannot_be_reused_for_different_payload(db_session):
    db, project_id = db_session
    coverage, events = load_heaven_ship_81_documents(ARCHIVE)
    kwargs = dict(project_id=project_id, archive_path=ARCHIVE,
                  coverage_document=coverage, events_document=events,
                  idempotency_key="same-key")
    first = import_coverage_documents(db, **kwargs)
    changed = dict(coverage)
    changed["summary"] = {"changed": True}
    with pytest.raises(PersistenceImportError, match="different input"):
        import_coverage_documents(db, **{**kwargs, "coverage_document": changed})
    assert db.scalar(select(func.count()).select_from(IntegrationRun)) == 1
    assert db.get(IntegrationRun, first) is not None


def test_export_detects_raw_snapshot_tampering(db_session):
    db, project_id = db_session
    coverage, events = load_heaven_ship_81_documents(ARCHIVE)
    run_id = import_coverage_documents(
        db, project_id=project_id, archive_path=ARCHIVE,
        coverage_document=coverage, events_document=events,
        idempotency_key="tamper-check",
    )
    row = db.scalar(select(IntegrationObjectSnapshot).where(
        IntegrationObjectSnapshot.integration_run_id == run_id,
        IntegrationObjectSnapshot.source_object_type == "dramatic_event",
    ))
    row.raw_payload = {**row.raw_payload, "observable_action": "tampered"}
    db.commit()
    with pytest.raises(PersistenceImportError, match="integrity check failed"):
        export_run_bundle(db, integration_run_id=run_id)
