"""Core projects, canonical entities, immutable versions and approval governance.

Revision ID: 0001_core
Revises: None
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0001_core"
down_revision = None
branch_labels = None
depends_on = None

def upgrade():
    bind = op.get_bind()
    uuid_type = sa.Uuid(as_uuid=True)
    json_type = sa.JSON()
    member_role = sa.Enum("owner", "producer", "director", "department_lead", "collaborator", "viewer", name="member_role")
    approval_status = sa.Enum("pending", "approved", "rejected", "changes_requested", "withdrawn", name="approval_status")

    op.create_table("projects",
        sa.Column("id", uuid_type, primary_key=True), sa.Column("code", sa.String(32), nullable=False, unique=True),
        sa.Column("name", sa.String(200), nullable=False), sa.Column("description", sa.Text()),
        sa.Column("status", sa.String(24), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False))
    op.create_table("project_members",
        sa.Column("id", uuid_type, primary_key=True), sa.Column("project_id", uuid_type, sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("principal_id", uuid_type, nullable=False), sa.Column("role", member_role, nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("project_id", "principal_id", name="uq_project_members_project_principal"))
    op.create_table("entities",
        sa.Column("id", uuid_type, primary_key=True), sa.Column("project_id", uuid_type, sa.ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("entity_type", sa.String(48), nullable=False), sa.Column("business_code", sa.String(48)),
        sa.Column("title", sa.String(240), nullable=False), sa.Column("lifecycle_state", sa.String(24), nullable=False),
        sa.Column("created_by", uuid_type), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False), sa.Column("archived_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("project_id", "id", name="uq_entities_project_id_id"), sa.CheckConstraint("length(entity_type) > 0", name="ck_entities_entity_type_nonempty"))
    op.create_index("ix_entities_project_type", "entities", ["project_id", "entity_type"])
    op.create_table("entity_versions",
        sa.Column("id", uuid_type, primary_key=True), sa.Column("project_id", uuid_type, nullable=False), sa.Column("entity_id", uuid_type, nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False), sa.Column("content", json_type, nullable=False), sa.Column("content_sha256", sa.String(64), nullable=False),
        sa.Column("parent_version_id", uuid_type), sa.Column("change_summary", sa.Text()), sa.Column("created_by", uuid_type), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["project_id", "entity_id"], ["entities.project_id", "entities.id"], ondelete="RESTRICT", name="fk_entity_versions_project_entity"),
        sa.ForeignKeyConstraint(["project_id", "entity_id", "parent_version_id"], ["entity_versions.project_id", "entity_versions.entity_id", "entity_versions.id"], ondelete="RESTRICT", name="fk_entity_versions_parent_same_entity"),
        sa.UniqueConstraint("project_id", "entity_id", "version_number", name="uq_entity_versions_number"),
        sa.UniqueConstraint("project_id", "entity_id", "id", name="uq_entity_versions_project_entity_id"),
        sa.CheckConstraint("version_number > 0", name="ck_entity_versions_version_number_positive"))
    op.create_index("ix_entity_versions_entity_created", "entity_versions", ["entity_id", "created_at"])
    op.create_table("entity_version_pointers",
        sa.Column("id", uuid_type, primary_key=True), sa.Column("project_id", uuid_type, nullable=False), sa.Column("entity_id", uuid_type, nullable=False),
        sa.Column("working_version_id", uuid_type), sa.Column("approved_version_id", uuid_type), sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["project_id", "entity_id"], ["entities.project_id", "entities.id"], ondelete="CASCADE", name="fk_version_pointers_entity"),
        sa.ForeignKeyConstraint(["project_id", "entity_id", "working_version_id"], ["entity_versions.project_id", "entity_versions.entity_id", "entity_versions.id"], ondelete="RESTRICT", name="fk_version_pointers_working_version"),
        sa.ForeignKeyConstraint(["project_id", "entity_id", "approved_version_id"], ["entity_versions.project_id", "entity_versions.entity_id", "entity_versions.id"], ondelete="RESTRICT", name="fk_version_pointers_approved_version"),
        sa.UniqueConstraint("project_id", "entity_id", name="uq_entity_version_pointers_entity"))
    op.create_table("entity_relations",
        sa.Column("id", uuid_type, primary_key=True), sa.Column("project_id", uuid_type, nullable=False), sa.Column("source_entity_id", uuid_type, nullable=False),
        sa.Column("target_entity_id", uuid_type, nullable=False), sa.Column("relation_type", sa.String(48), nullable=False), sa.Column("attributes", json_type, nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["project_id", "source_entity_id"], ["entities.project_id", "entities.id"], ondelete="CASCADE", name="fk_entity_relations_source"),
        sa.ForeignKeyConstraint(["project_id", "target_entity_id"], ["entities.project_id", "entities.id"], ondelete="RESTRICT", name="fk_entity_relations_target"),
        sa.UniqueConstraint("project_id", "source_entity_id", "target_entity_id", "relation_type", name="uq_entity_relation_edge"), sa.CheckConstraint("source_entity_id <> target_entity_id", name="ck_entity_relations_relation_not_self"))
    op.create_table("audit_logs",
        sa.Column("id", uuid_type, primary_key=True), sa.Column("project_id", uuid_type, sa.ForeignKey("projects.id", ondelete="RESTRICT")),
        sa.Column("actor_id", uuid_type), sa.Column("actor_kind", sa.String(24), nullable=False), sa.Column("action", sa.String(64), nullable=False),
        sa.Column("object_type", sa.String(48), nullable=False), sa.Column("object_id", uuid_type), sa.Column("details", json_type, nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))
    op.create_index("ix_audit_logs_project_created", "audit_logs", ["project_id", "created_at"])
    op.create_table("approval_workflows",
        sa.Column("id", uuid_type, primary_key=True), sa.Column("project_id", uuid_type, sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("code", sa.String(48), nullable=False), sa.Column("name", sa.String(160), nullable=False), sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False), sa.UniqueConstraint("project_id", "code", name="uq_approval_workflow_project_code"),
        sa.UniqueConstraint("project_id", "id", name="uq_approval_workflows_project_id"))
    op.create_table("approval_steps",
        sa.Column("id", uuid_type, primary_key=True), sa.Column("workflow_id", uuid_type, sa.ForeignKey("approval_workflows.id", ondelete="CASCADE"), nullable=False),
        sa.Column("step_order", sa.Integer(), nullable=False), sa.Column("required_role", sa.String(32), nullable=False), sa.Column("is_required", sa.Boolean(), nullable=False),
        sa.UniqueConstraint("workflow_id", "step_order", name="uq_approval_steps_order"), sa.CheckConstraint("step_order > 0", name="ck_approval_steps_step_order_positive"))
    op.create_table("approval_records",
        sa.Column("id", uuid_type, primary_key=True), sa.Column("project_id", uuid_type, nullable=False), sa.Column("entity_id", uuid_type, nullable=False),
        sa.Column("entity_version_id", uuid_type, nullable=False), sa.Column("workflow_id", uuid_type, sa.ForeignKey("approval_workflows.id", ondelete="RESTRICT")),
        sa.Column("step_order", sa.Integer(), nullable=False), sa.Column("reviewer_id", uuid_type, nullable=False), sa.Column("status", approval_status, nullable=False),
        sa.Column("decision_note", sa.Text()), sa.Column("decided_at", sa.DateTime(timezone=True)), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["project_id", "entity_id", "entity_version_id"], ["entity_versions.project_id", "entity_versions.entity_id", "entity_versions.id"], ondelete="RESTRICT", name="fk_approval_records_version"),
        sa.ForeignKeyConstraint(["project_id", "workflow_id"], ["approval_workflows.project_id", "approval_workflows.id"], ondelete="RESTRICT", name="fk_approval_records_workflow_same_project"),
        sa.CheckConstraint("step_order > 0", name="ck_approval_records_approval_record_step_order_positive"))
    op.create_index("ix_approval_records_version_status", "approval_records", ["entity_version_id", "status"])
    op.create_table("entity_dependencies",
        sa.Column("id", uuid_type, primary_key=True), sa.Column("project_id", uuid_type, nullable=False), sa.Column("source_entity_id", uuid_type, nullable=False),
        sa.Column("dependent_entity_id", uuid_type, nullable=False), sa.Column("dependency_type", sa.String(48), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["project_id", "source_entity_id"], ["entities.project_id", "entities.id"], ondelete="CASCADE", name="fk_entity_dependencies_source"),
        sa.ForeignKeyConstraint(["project_id", "dependent_entity_id"], ["entities.project_id", "entities.id"], ondelete="RESTRICT", name="fk_entity_dependencies_dependent"),
        sa.UniqueConstraint("project_id", "source_entity_id", "dependent_entity_id", "dependency_type", name="uq_entity_dependency_edge"), sa.CheckConstraint("source_entity_id <> dependent_entity_id", name="ck_entity_dependencies_dependency_not_self"))
    op.create_table("change_impact_reports",
        sa.Column("id", uuid_type, primary_key=True), sa.Column("project_id", uuid_type, sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source_entity_id", uuid_type, nullable=False), sa.Column("source_version_id", uuid_type, nullable=False), sa.Column("impact_graph", json_type, nullable=False),
        sa.Column("recommendation", sa.Text()), sa.Column("human_decision", sa.String(32)), sa.Column("decided_by", uuid_type), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["project_id", "source_entity_id"], ["entities.project_id", "entities.id"], ondelete="RESTRICT", name="fk_change_impact_source_entity"),
        sa.ForeignKeyConstraint(["project_id", "source_entity_id", "source_version_id"], ["entity_versions.project_id", "entity_versions.entity_id", "entity_versions.id"], ondelete="RESTRICT", name="fk_change_impact_source_version"))
    op.create_index("ix_change_impact_project_created", "change_impact_reports", ["project_id", "created_at"])

    # Immutable entity-version rows: only PostgreSQL production migration enforces this trigger.
    if bind.dialect.name == "postgresql":
        op.execute("""CREATE OR REPLACE FUNCTION afs_reject_entity_version_mutation() RETURNS trigger AS $$ BEGIN RAISE EXCEPTION 'entity_versions are immutable; create a new version'; END; $$ LANGUAGE plpgsql""")
        op.execute("CREATE TRIGGER trg_entity_versions_immutable BEFORE UPDATE OR DELETE ON entity_versions FOR EACH ROW EXECUTE FUNCTION afs_reject_entity_version_mutation()")
    elif bind.dialect.name == "sqlite":
        op.execute("CREATE TRIGGER trg_entity_versions_no_update BEFORE UPDATE ON entity_versions BEGIN SELECT RAISE(ABORT, 'entity_versions are immutable; create a new version'); END")
        op.execute("CREATE TRIGGER trg_entity_versions_no_delete BEFORE DELETE ON entity_versions BEGIN SELECT RAISE(ABORT, 'entity_versions are immutable; create a new version'); END")

def downgrade():
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("DROP TRIGGER IF EXISTS trg_entity_versions_immutable ON entity_versions")
        op.execute("DROP FUNCTION IF EXISTS afs_reject_entity_version_mutation()")
    elif bind.dialect.name == "sqlite":
        op.execute("DROP TRIGGER IF EXISTS trg_entity_versions_no_update")
        op.execute("DROP TRIGGER IF EXISTS trg_entity_versions_no_delete")
    for name in ["change_impact_reports", "entity_dependencies", "approval_records", "approval_steps", "approval_workflows", "audit_logs", "entity_relations", "entity_version_pointers", "entity_versions", "entities", "project_members", "projects"]:
        op.drop_table(name)
    if bind.dialect.name == "postgresql":
        sa.Enum(name="approval_status").drop(bind, checkfirst=True)
        sa.Enum(name="member_role").drop(bind, checkfirst=True)
