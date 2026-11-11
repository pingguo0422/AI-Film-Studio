"""Footage-Mode 2.2-B source-validation/import Skill for AFS Agent Runtime.

This skill imports the package's existing Heaven Ship 8.1 event/coverage outputs.
It does not rerun the optimizer or claim a new model-generated shot plan.
"""
from __future__ import annotations
from pathlib import Path
from typing import Callable
from uuid import UUID
from sqlalchemy.orm import Session
from .adapter import FootageModeAdapter
from .persistence import load_heaven_ship_81_documents, import_coverage_documents, export_run_bundle


def build_heaven_ship_81_validation_executor(*, session_factory: Callable[[], Session], archive_path: str | Path):
    archive=Path(archive_path).resolve()
    descriptor=FootageModeAdapter().inspect_source(archive)
    coverage,events=load_heaven_ship_81_documents(archive)
    def execute(input_snapshot: dict) -> dict:
        project_raw=input_snapshot.get("project_id")
        task_raw=input_snapshot.get("task_id")
        if not project_raw or not task_raw: raise ValueError("project_id and task_id are required in task input")
        project_id=UUID(str(project_raw)); task_id=UUID(str(task_raw))
        with session_factory() as db:
            run_id=import_coverage_documents(db,project_id=project_id,archive_path=archive,
                coverage_document=coverage,events_document=events,
                idempotency_key=f"afs-agent-task:{task_id}:fm22b-81")
            bundle=export_run_bundle(db,integration_run_id=run_id)
            db.commit()
        if bundle["run"]["event_count"] != 52 or bundle["run"]["decision_count"] != 52:
            raise ValueError("Heaven Ship 8.1 source event/decision parity validation failed")
        if bundle["run"]["source_kind"] != "SOURCE_ACTING_TASK":
            raise ValueError("unexpected source provenance; expected SOURCE_ACTING_TASK")
        if bundle["run"]["human_approval"] is not False:
            raise ValueError("imported Footage-Mode proposal must remain unapproved")
        return {
            "operation":"footage_mode_8_1_source_validation_and_import",
            "package":{"name":descriptor.name,"version":descriptor.version,"release_status":descriptor.release_status,"sha256":descriptor.archive_sha256},
            "integration_run_id":bundle["run"]["id"],
            "source_kind":bundle["run"]["source_kind"],
            "event_count":bundle["run"]["event_count"],
            "decision_count":bundle["run"]["decision_count"],
            "canonical_links_status":bundle["canonical_links"]["status"],
            "human_approval":False,
            "result_semantics":"existing Footage-Mode output imported and validated; optimizer/model was not rerun",
        }
    return execute
