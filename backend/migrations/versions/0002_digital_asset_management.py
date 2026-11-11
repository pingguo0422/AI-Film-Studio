"""AFS-DAM objects, asset versions, provenance, processing jobs and QC.

Revision ID: 0002_dam
Revises: 0001_core
"""
from alembic import op
import sqlalchemy as sa

revision = "0002_dam"
down_revision = "0001_core"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    u = sa.Uuid(as_uuid=True)
    j = sa.JSON()

    op.create_table(
        "media_objects",
        sa.Column("id", u, primary_key=True),
        sa.Column("storage_provider", sa.String(32), nullable=False),
        sa.Column("bucket", sa.String(128), nullable=False),
        sa.Column("storage_key", sa.String(512), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("byte_size", sa.Integer(), nullable=False),
        sa.Column("mime_type", sa.String(160), nullable=False),
        sa.Column("object_state", sa.String(24), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_verified_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("storage_provider", "bucket", "storage_key", name="uq_media_objects_storage_locator"),
        sa.CheckConstraint("byte_size >= 0", name="ck_media_objects_media_object_byte_size_nonnegative"),
        sa.CheckConstraint("length(sha256) = 64", name="ck_media_objects_media_object_sha256_length"),
        sa.CheckConstraint("object_state IN ('staged', 'available', 'delete_pending', 'deleted', 'failed')", name="ck_media_objects_media_object_state_valid"),
    )
    op.create_index("ix_media_objects_sha_size", "media_objects", ["sha256", "byte_size"])

    op.create_table(
        "media_assets",
        sa.Column("id", u, primary_key=True),
        sa.Column("project_id", u, nullable=False),
        sa.Column("entity_id", u, nullable=False),
        sa.Column("asset_kind", sa.String(32), nullable=False),
        sa.Column("title", sa.String(240), nullable=False),
        sa.Column("lifecycle_state", sa.String(24), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["project_id", "entity_id"], ["entities.project_id", "entities.id"], ondelete="RESTRICT", name="fk_media_assets_entity"),
        sa.UniqueConstraint("project_id", "id", name="uq_media_assets_project_id_id"),
        sa.UniqueConstraint("project_id", "entity_id", name="uq_media_assets_project_entity"),
    )
    op.create_index("ix_media_assets_project_kind", "media_assets", ["project_id", "asset_kind"])

    op.create_table(
        "media_asset_versions",
        sa.Column("id", u, primary_key=True),
        sa.Column("project_id", u, nullable=False),
        sa.Column("asset_id", u, nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("media_object_id", u, nullable=False),
        sa.Column("parent_version_id", u),
        sa.Column("original_filename", sa.String(512), nullable=False),
        sa.Column("metadata_snapshot", j, nullable=False),
        sa.Column("created_by", u),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["project_id", "asset_id"], ["media_assets.project_id", "media_assets.id"], ondelete="RESTRICT", name="fk_media_asset_versions_asset"),
        sa.ForeignKeyConstraint(["project_id", "asset_id", "parent_version_id"], ["media_asset_versions.project_id", "media_asset_versions.asset_id", "media_asset_versions.id"], ondelete="RESTRICT", name="fk_media_asset_versions_parent_same_asset"),
        sa.ForeignKeyConstraint(["media_object_id"], ["media_objects.id"], ondelete="RESTRICT", name="fk_media_asset_versions_object"),
        sa.UniqueConstraint("project_id", "asset_id", "version_number", name="uq_media_asset_versions_number"),
        sa.UniqueConstraint("project_id", "asset_id", "id", name="uq_media_asset_versions_project_asset_id"),
        sa.CheckConstraint("version_number > 0", name="ck_media_asset_versions_media_asset_version_number_positive"),
    )
    op.create_index("ix_media_asset_versions_asset_created", "media_asset_versions", ["asset_id", "created_at"])

    op.create_table(
        "media_asset_pointers",
        sa.Column("id", u, primary_key=True),
        sa.Column("project_id", u, nullable=False),
        sa.Column("asset_id", u, nullable=False),
        sa.Column("working_version_id", u),
        sa.Column("approved_version_id", u),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["project_id", "asset_id"], ["media_assets.project_id", "media_assets.id"], ondelete="CASCADE", name="fk_media_asset_pointers_asset"),
        sa.ForeignKeyConstraint(["project_id", "asset_id", "working_version_id"], ["media_asset_versions.project_id", "media_asset_versions.asset_id", "media_asset_versions.id"], ondelete="RESTRICT", name="fk_media_asset_pointers_working"),
        sa.ForeignKeyConstraint(["project_id", "asset_id", "approved_version_id"], ["media_asset_versions.project_id", "media_asset_versions.asset_id", "media_asset_versions.id"], ondelete="RESTRICT", name="fk_media_asset_pointers_approved"),
        sa.UniqueConstraint("project_id", "asset_id", name="uq_media_asset_pointers_asset"),
    )

    op.create_table(
        "media_asset_relations",
        sa.Column("id", u, primary_key=True),
        sa.Column("project_id", u, nullable=False),
        sa.Column("source_asset_id", u, nullable=False),
        sa.Column("target_asset_id", u, nullable=False),
        sa.Column("relation_type", sa.String(48), nullable=False),
        sa.Column("attributes", j, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["project_id", "source_asset_id"], ["media_assets.project_id", "media_assets.id"], ondelete="CASCADE", name="fk_media_asset_relations_source"),
        sa.ForeignKeyConstraint(["project_id", "target_asset_id"], ["media_assets.project_id", "media_assets.id"], ondelete="RESTRICT", name="fk_media_asset_relations_target"),
        sa.UniqueConstraint("project_id", "source_asset_id", "target_asset_id", "relation_type", name="uq_media_asset_relation_edge"),
        sa.CheckConstraint("source_asset_id <> target_asset_id", name="ck_media_asset_relations_media_asset_relation_not_self"),
    )

    op.create_table(
        "media_provenance",
        sa.Column("id", u, primary_key=True),
        sa.Column("project_id", u, nullable=False),
        sa.Column("asset_id", u, nullable=False),
        sa.Column("asset_version_id", u, nullable=False),
        sa.Column("producer_kind", sa.String(24), nullable=False),
        sa.Column("producer_id", u),
        sa.Column("execution_snapshot", j, nullable=False),
        sa.Column("input_asset_versions", j, nullable=False),
        sa.Column("parameters", j, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["project_id", "asset_id", "asset_version_id"], ["media_asset_versions.project_id", "media_asset_versions.asset_id", "media_asset_versions.id"], ondelete="RESTRICT", name="fk_media_provenance_asset_version"),
    )
    op.create_index("ix_media_provenance_version", "media_provenance", ["asset_version_id"])

    op.create_table(
        "media_processing_jobs",
        sa.Column("id", u, primary_key=True),
        sa.Column("project_id", u, nullable=False),
        sa.Column("asset_id", u),
        sa.Column("asset_version_id", u),
        sa.Column("job_type", sa.String(48), nullable=False),
        sa.Column("idempotency_key", sa.String(128), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("request_snapshot", j, nullable=False),
        sa.Column("result_snapshot", j),
        sa.Column("error_detail", j),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["project_id", "asset_id", "asset_version_id"], ["media_asset_versions.project_id", "media_asset_versions.asset_id", "media_asset_versions.id"], ondelete="RESTRICT", name="fk_media_processing_jobs_asset_version"),
        sa.UniqueConstraint("project_id", "idempotency_key", name="uq_media_processing_jobs_idempotency"),
        sa.CheckConstraint("attempt_count >= 0", name="ck_media_processing_jobs_media_processing_attempt_nonnegative"),
        sa.CheckConstraint("(asset_id IS NULL AND asset_version_id IS NULL) OR (asset_id IS NOT NULL AND asset_version_id IS NOT NULL)", name="ck_media_processing_jobs_media_processing_asset_version_pair"),
        sa.CheckConstraint("status IN ('queued', 'running', 'succeeded', 'failed', 'cancelled')", name="ck_media_processing_jobs_media_processing_status_valid"),
    )
    op.create_index("ix_media_processing_jobs_status_created", "media_processing_jobs", ["status", "created_at"])

    op.create_table(
        "media_qc_records",
        sa.Column("id", u, primary_key=True),
        sa.Column("project_id", u, nullable=False),
        sa.Column("asset_id", u, nullable=False),
        sa.Column("asset_version_id", u, nullable=False),
        sa.Column("qc_type", sa.String(24), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("findings", j, nullable=False),
        sa.Column("tool_snapshot", j, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["project_id", "asset_id", "asset_version_id"], ["media_asset_versions.project_id", "media_asset_versions.asset_id", "media_asset_versions.id"], ondelete="RESTRICT", name="fk_media_qc_asset_version"),
        sa.CheckConstraint("qc_type IN ('technical', 'artistic')", name="ck_media_qc_records_qc_type"),
        sa.CheckConstraint("status IN ('pass', 'warning', 'fail', 'incomplete')", name="ck_media_qc_records_status"),
    )
    op.create_index("ix_media_qc_version_type_created", "media_qc_records", ["asset_version_id", "qc_type", "created_at"])

    if bind.dialect.name == "postgresql":
        op.execute("""CREATE OR REPLACE FUNCTION afs_reject_media_asset_version_mutation() RETURNS trigger AS $$ BEGIN RAISE EXCEPTION 'media_asset_versions are immutable; create a new version'; END; $$ LANGUAGE plpgsql""")
        op.execute("CREATE TRIGGER trg_media_asset_versions_immutable BEFORE UPDATE OR DELETE ON media_asset_versions FOR EACH ROW EXECUTE FUNCTION afs_reject_media_asset_version_mutation()")
        op.execute("""CREATE OR REPLACE FUNCTION afs_reject_media_object_identity_change() RETURNS trigger AS $$ BEGIN IF (NEW.storage_provider, NEW.bucket, NEW.storage_key, NEW.sha256, NEW.byte_size, NEW.mime_type) IS DISTINCT FROM (OLD.storage_provider, OLD.bucket, OLD.storage_key, OLD.sha256, OLD.byte_size, OLD.mime_type) THEN RAISE EXCEPTION 'media object identity is immutable'; END IF; RETURN NEW; END; $$ LANGUAGE plpgsql""")
        op.execute("CREATE TRIGGER trg_media_objects_identity_immutable BEFORE UPDATE ON media_objects FOR EACH ROW EXECUTE FUNCTION afs_reject_media_object_identity_change()")
    elif bind.dialect.name == "sqlite":
        op.execute("CREATE TRIGGER trg_media_asset_versions_no_update BEFORE UPDATE ON media_asset_versions BEGIN SELECT RAISE(ABORT, 'media_asset_versions are immutable; create a new version'); END")
        op.execute("CREATE TRIGGER trg_media_asset_versions_no_delete BEFORE DELETE ON media_asset_versions BEGIN SELECT RAISE(ABORT, 'media_asset_versions are immutable; create a new version'); END")
        op.execute("CREATE TRIGGER trg_media_objects_identity_immutable BEFORE UPDATE OF storage_provider, bucket, storage_key, sha256, byte_size, mime_type ON media_objects BEGIN SELECT RAISE(ABORT, 'media object identity is immutable'); END")


def downgrade():
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("DROP TRIGGER IF EXISTS trg_media_asset_versions_immutable ON media_asset_versions")
        op.execute("DROP FUNCTION IF EXISTS afs_reject_media_asset_version_mutation()")
        op.execute("DROP TRIGGER IF EXISTS trg_media_objects_identity_immutable ON media_objects")
        op.execute("DROP FUNCTION IF EXISTS afs_reject_media_object_identity_change()")
    elif bind.dialect.name == "sqlite":
        for trigger in ["trg_media_asset_versions_no_update", "trg_media_asset_versions_no_delete", "trg_media_objects_identity_immutable"]:
            op.execute(f"DROP TRIGGER IF EXISTS {trigger}")
    for table in ["media_qc_records", "media_processing_jobs", "media_provenance", "media_asset_relations", "media_asset_pointers", "media_asset_versions", "media_assets", "media_objects"]:
        op.drop_table(table)
