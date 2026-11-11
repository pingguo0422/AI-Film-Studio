import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from backend.app.db.base import Base
from backend.app.db.ids import uuid7
from backend.app.models import Project, Entity, MediaObject, MediaAsset, MediaAssetVersion, MediaAssetPointer, MediaProcessingJob

def make_db():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    @event.listens_for(engine, "connect")
    def enable_fk(dbapi_connection, _):
        dbapi_connection.execute("PRAGMA foreign_keys=ON")
    Base.metadata.create_all(engine)
    return engine

def seed_asset(db, project_id, entity_id, asset_id, title):
    db.add(Entity(id=entity_id, project_id=project_id, entity_type="MEDIA_ASSET", title=title))
    db.flush()
    db.add(MediaAsset(id=asset_id, project_id=project_id, entity_id=entity_id, asset_kind="image", title=title))
    db.flush()

def test_dam_asset_version_and_pointer_invariants():
    engine=make_db(); p=uuid7(); e1=uuid7(); a1=uuid7(); obj=uuid7(); v1=uuid7()
    with Session(engine) as db:
        db.add(Project(id=p, code="PRJ_DAM", name="DAM test")); db.flush()
        seed_asset(db,p,e1,a1,"Key art")
        db.add(MediaObject(id=obj, storage_provider="s3", bucket="afs-dev", storage_key="project/a1/v1", sha256="c"*64, byte_size=123, mime_type="image/png", object_state="available")); db.flush()
        db.add(MediaAssetVersion(id=v1, project_id=p, asset_id=a1, version_number=1, media_object_id=obj, original_filename="key-art.png", metadata_snapshot={"width":1024}))
        db.flush()
        db.add(MediaAssetPointer(project_id=p, asset_id=a1, working_version_id=v1))
        db.commit()
        assert db.query(MediaAssetPointer).filter_by(asset_id=a1).one().working_version_id == v1
        with pytest.raises(IntegrityError):
            db.delete(db.get(MediaObject,obj)); db.commit()
        db.rollback()

def test_dam_job_idempotency_key_is_unique_per_project():
    engine=make_db(); p=uuid7()
    with Session(engine) as db:
        db.add(Project(id=p, code="PRJ_DAM_JOB", name="DAM job")); db.flush()
        db.add(MediaProcessingJob(project_id=p, job_type="thumbnail", idempotency_key="same-key", status="queued", attempt_count=0, request_snapshot={}))
        db.add(MediaProcessingJob(project_id=p, job_type="thumbnail", idempotency_key="same-key", status="queued", attempt_count=0, request_snapshot={}))
        with pytest.raises(IntegrityError):
            db.commit()
