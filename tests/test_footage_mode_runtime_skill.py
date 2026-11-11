from pathlib import Path
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker
from backend.app.db.base import Base
from backend.app.db.ids import uuid7
from backend.app.models import Project
from integrations.footage_mode.skill import build_heaven_ship_81_validation_executor

ROOT=Path(__file__).resolve().parents[1]
ARCHIVE=ROOT/"source-baseline"/"Footage-Mode-2.2-B.zip"

def test_footage_mode_81_skill_imports_and_preserves_proposal_semantics():
    engine=create_engine("sqlite+pysqlite:///:memory:")
    @event.listens_for(engine,"connect")
    def fk(conn,_): conn.execute("PRAGMA foreign_keys=ON")
    Base.metadata.create_all(engine); Factory=sessionmaker(engine,expire_on_commit=False)
    with Factory() as db:
        project=Project(id=uuid7(),code="PRJ_FM_SKILL",name="Heaven Ship")
        db.add(project); db.commit(); project_id=project.id
    executor=build_heaven_ship_81_validation_executor(session_factory=Factory,archive_path=ARCHIVE)
    result=executor({"project_id":str(project_id),"task_id":str(uuid7())})
    assert result["event_count"]==52 and result["decision_count"]==52
    assert result["source_kind"]=="SOURCE_ACTING_TASK"
    assert result["human_approval"] is False
    assert result["result_semantics"].startswith("existing Footage-Mode output imported")
