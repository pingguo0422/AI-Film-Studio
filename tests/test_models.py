from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import Session
from backend.app.db.base import Base
from backend.app.db.ids import uuid7
from backend.app.models import Project, Entity, EntityVersion, EntityVersionPointer, EntityRelation

def test_core_schema_creates_on_sqlite():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    names = set(inspect(engine).get_table_names())
    assert {"projects", "entities", "entity_versions", "entity_version_pointers", "approval_records", "audit_logs"} <= names

def test_version_pointer_rejects_cross_entity_version():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with engine.begin() as conn:
        conn.exec_driver_sql("PRAGMA foreign_keys=ON")
    p = uuid7(); e1 = uuid7(); e2 = uuid7(); v1 = uuid7()
    with Session(engine) as s:
        s.add(Project(id=p, code="PRJ_TEST", name="Test")); s.flush()
        s.add_all([Entity(id=e1, project_id=p, entity_type="CHARACTER", title="A"), Entity(id=e2, project_id=p, entity_type="CHARACTER", title="B")]); s.flush()
        s.add(EntityVersion(id=v1, project_id=p, entity_id=e1, version_number=1, content={"name":"A"}, content_sha256="a"*64)); s.flush()
        s.add(EntityVersionPointer(project_id=p, entity_id=e2, working_version_id=v1))
        try:
            s.commit()
        except Exception:
            s.rollback()
            return
        raise AssertionError("cross-entity version pointer should violate composite FK")

def test_entity_version_parent_must_belong_to_same_entity():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    from sqlalchemy import event
    @event.listens_for(engine, "connect")
    def enable_fk(dbapi_connection, _):
        dbapi_connection.execute("PRAGMA foreign_keys=ON")
    Base.metadata.create_all(engine)
    p = uuid7(); e1 = uuid7(); e2 = uuid7(); v1 = uuid7(); v2 = uuid7()
    with Session(engine) as s:
        s.add(Project(id=p, code="PRJ_PARENT", name="Parent test")); s.flush()
        s.add_all([Entity(id=e1, project_id=p, entity_type="CHARACTER", title="A"), Entity(id=e2, project_id=p, entity_type="CHARACTER", title="B")]); s.flush()
        s.add(EntityVersion(id=v1, project_id=p, entity_id=e1, version_number=1, content={}, content_sha256="1"*64)); s.flush()
        s.add(EntityVersion(id=v2, project_id=p, entity_id=e2, version_number=1, content={}, content_sha256="2"*64, parent_version_id=v1))
        try:
            s.commit()
        except Exception:
            s.rollback()
            return
        raise AssertionError("parent version must belong to the same entity")
