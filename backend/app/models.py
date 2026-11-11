"""AFS canonical core models — DB-01 and DB-02 first implementation slice."""
from __future__ import annotations
import enum
from datetime import datetime, timezone
from sqlalchemy import (
    Boolean, CheckConstraint, DateTime, Enum, Float, ForeignKey, ForeignKeyConstraint,
    Index, Integer, JSON, String, Text, UniqueConstraint, Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column
from backend.app.db.base import Base
from backend.app.db.ids import uuid7

def utcnow():
    return datetime.now(timezone.utc)

class MemberRole(str, enum.Enum):
    owner = "owner"
    producer = "producer"
    director = "director"
    department_lead = "department_lead"
    collaborator = "collaborator"
    viewer = "viewer"

class ApprovalStatus(str, enum.Enum):
    pending = "pending"
    approved = "approved"
    rejected = "rejected"
    changes_requested = "changes_requested"
    withdrawn = "withdrawn"

class Project(Base):
    __tablename__ = "projects"
    id: Mapped[object] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid7)
    code: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)

class ProjectMember(Base):
    __tablename__ = "project_members"
    __table_args__ = (UniqueConstraint("project_id", "principal_id", name="uq_project_members_project_principal"),)
    id: Mapped[object] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid7)
    project_id: Mapped[object] = mapped_column(Uuid(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    principal_id: Mapped[object] = mapped_column(Uuid(as_uuid=True), ForeignKey("principals.id", ondelete="RESTRICT"), nullable=False)
    role: Mapped[MemberRole] = mapped_column(Enum(MemberRole, name="member_role"), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)

class Entity(Base):
    __tablename__ = "entities"
    __table_args__ = (
        UniqueConstraint("project_id", "id", name="uq_entities_project_id_id"),
        Index("ix_entities_project_type", "project_id", "entity_type"),
        CheckConstraint("length(entity_type) > 0", name="entity_type_nonempty"),
    )
    id: Mapped[object] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid7)
    project_id: Mapped[object] = mapped_column(Uuid(as_uuid=True), ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(48), nullable=False)
    business_code: Mapped[str | None] = mapped_column(String(48))
    title: Mapped[str] = mapped_column(String(240), nullable=False)
    lifecycle_state: Mapped[str] = mapped_column(String(24), nullable=False, default="active")
    created_by: Mapped[object | None] = mapped_column(Uuid(as_uuid=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

class EntityVersion(Base):
    __tablename__ = "entity_versions"
    __table_args__ = (
        UniqueConstraint("project_id", "entity_id", "version_number", name="uq_entity_versions_number"),
        UniqueConstraint("project_id", "entity_id", "id", name="uq_entity_versions_project_entity_id"),
        CheckConstraint("version_number > 0", name="version_number_positive"),
        Index("ix_entity_versions_entity_created", "entity_id", "created_at"),
        ForeignKeyConstraint(["project_id", "entity_id"], ["entities.project_id", "entities.id"], ondelete="RESTRICT", name="fk_entity_versions_project_entity"),
        ForeignKeyConstraint(["project_id", "entity_id", "parent_version_id"], ["entity_versions.project_id", "entity_versions.entity_id", "entity_versions.id"], ondelete="RESTRICT", name="fk_entity_versions_parent_same_entity"),
    )
    id: Mapped[object] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid7)
    project_id: Mapped[object] = mapped_column(Uuid(as_uuid=True), nullable=False)
    entity_id: Mapped[object] = mapped_column(Uuid(as_uuid=True), nullable=False)
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[dict] = mapped_column(JSON, nullable=False)
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    parent_version_id: Mapped[object | None] = mapped_column(Uuid(as_uuid=True))
    change_summary: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[object | None] = mapped_column(Uuid(as_uuid=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)

class EntityVersionPointer(Base):
    """Separate mutable pointers keep immutable version rows free of workflow state."""
    __tablename__ = "entity_version_pointers"
    __table_args__ = (
        UniqueConstraint("project_id", "entity_id", name="uq_entity_version_pointers_entity"),
        ForeignKeyConstraint(["project_id", "entity_id"], ["entities.project_id", "entities.id"], ondelete="CASCADE", name="fk_version_pointers_entity"),
        ForeignKeyConstraint(["project_id", "entity_id", "working_version_id"], ["entity_versions.project_id", "entity_versions.entity_id", "entity_versions.id"], ondelete="RESTRICT", name="fk_version_pointers_working_version"),
        ForeignKeyConstraint(["project_id", "entity_id", "approved_version_id"], ["entity_versions.project_id", "entity_versions.entity_id", "entity_versions.id"], ondelete="RESTRICT", name="fk_version_pointers_approved_version"),
    )
    id: Mapped[object] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid7)
    project_id: Mapped[object] = mapped_column(Uuid(as_uuid=True), nullable=False)
    entity_id: Mapped[object] = mapped_column(Uuid(as_uuid=True), nullable=False)
    working_version_id: Mapped[object | None] = mapped_column(Uuid(as_uuid=True))
    approved_version_id: Mapped[object | None] = mapped_column(Uuid(as_uuid=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)

class EntityRelation(Base):
    __tablename__ = "entity_relations"
    __table_args__ = (
        ForeignKeyConstraint(["project_id", "source_entity_id"], ["entities.project_id", "entities.id"], ondelete="CASCADE", name="fk_entity_relations_source"),
        ForeignKeyConstraint(["project_id", "target_entity_id"], ["entities.project_id", "entities.id"], ondelete="RESTRICT", name="fk_entity_relations_target"),
        UniqueConstraint("project_id", "source_entity_id", "target_entity_id", "relation_type", name="uq_entity_relation_edge"),
        CheckConstraint("source_entity_id <> target_entity_id", name="relation_not_self"),
    )
    id: Mapped[object] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid7)
    project_id: Mapped[object] = mapped_column(Uuid(as_uuid=True), nullable=False)
    source_entity_id: Mapped[object] = mapped_column(Uuid(as_uuid=True), nullable=False)
    target_entity_id: Mapped[object] = mapped_column(Uuid(as_uuid=True), nullable=False)
    relation_type: Mapped[str] = mapped_column(String(48), nullable=False)
    attributes: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)

class AuditLog(Base):
    __tablename__ = "audit_logs"
    __table_args__ = (Index("ix_audit_logs_project_created", "project_id", "created_at"),)
    id: Mapped[object] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid7)
    project_id: Mapped[object | None] = mapped_column(Uuid(as_uuid=True), ForeignKey("projects.id", ondelete="RESTRICT"))
    actor_id: Mapped[object | None] = mapped_column(Uuid(as_uuid=True))
    actor_kind: Mapped[str] = mapped_column(String(24), nullable=False)
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    object_type: Mapped[str] = mapped_column(String(48), nullable=False)
    object_id: Mapped[object | None] = mapped_column(Uuid(as_uuid=True))
    details: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)

class ApprovalWorkflow(Base):
    __tablename__ = "approval_workflows"
    __table_args__ = (
        UniqueConstraint("project_id", "code", name="uq_approval_workflow_project_code"),
        UniqueConstraint("project_id", "id", name="uq_approval_workflows_project_id"),
    )
    id: Mapped[object] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid7)
    project_id: Mapped[object] = mapped_column(Uuid(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    code: Mapped[str] = mapped_column(String(48), nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)

class ApprovalStep(Base):
    __tablename__ = "approval_steps"
    __table_args__ = (UniqueConstraint("workflow_id", "step_order", name="uq_approval_steps_order"), CheckConstraint("step_order > 0", name="step_order_positive"))
    id: Mapped[object] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid7)
    workflow_id: Mapped[object] = mapped_column(Uuid(as_uuid=True), ForeignKey("approval_workflows.id", ondelete="CASCADE"), nullable=False)
    step_order: Mapped[int] = mapped_column(Integer, nullable=False)
    required_role: Mapped[str] = mapped_column(String(32), nullable=False)
    is_required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

class ApprovalRecord(Base):
    __tablename__ = "approval_records"
    __table_args__ = (
        ForeignKeyConstraint(["project_id", "entity_id", "entity_version_id"], ["entity_versions.project_id", "entity_versions.entity_id", "entity_versions.id"], ondelete="RESTRICT", name="fk_approval_records_version"),
        ForeignKeyConstraint(["project_id", "workflow_id"], ["approval_workflows.project_id", "approval_workflows.id"], ondelete="RESTRICT", name="fk_approval_records_workflow_same_project"),
        CheckConstraint("step_order > 0", name="approval_record_step_order_positive"),
        Index("ix_approval_records_version_status", "entity_version_id", "status"),
    )
    id: Mapped[object] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid7)
    project_id: Mapped[object] = mapped_column(Uuid(as_uuid=True), nullable=False)
    entity_id: Mapped[object] = mapped_column(Uuid(as_uuid=True), nullable=False)
    entity_version_id: Mapped[object] = mapped_column(Uuid(as_uuid=True), nullable=False)
    workflow_id: Mapped[object | None] = mapped_column(Uuid(as_uuid=True), ForeignKey("approval_workflows.id", ondelete="RESTRICT"))
    step_order: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    reviewer_id: Mapped[object] = mapped_column(Uuid(as_uuid=True), nullable=False)
    status: Mapped[ApprovalStatus] = mapped_column(Enum(ApprovalStatus, name="approval_status"), nullable=False, default=ApprovalStatus.pending)
    decision_note: Mapped[str | None] = mapped_column(Text)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)

class EntityDependency(Base):
    __tablename__ = "entity_dependencies"
    __table_args__ = (
        ForeignKeyConstraint(["project_id", "source_entity_id"], ["entities.project_id", "entities.id"], ondelete="CASCADE", name="fk_entity_dependencies_source"),
        ForeignKeyConstraint(["project_id", "dependent_entity_id"], ["entities.project_id", "entities.id"], ondelete="RESTRICT", name="fk_entity_dependencies_dependent"),
        UniqueConstraint("project_id", "source_entity_id", "dependent_entity_id", "dependency_type", name="uq_entity_dependency_edge"),
        CheckConstraint("source_entity_id <> dependent_entity_id", name="dependency_not_self"),
    )
    id: Mapped[object] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid7)
    project_id: Mapped[object] = mapped_column(Uuid(as_uuid=True), nullable=False)
    source_entity_id: Mapped[object] = mapped_column(Uuid(as_uuid=True), nullable=False)
    dependent_entity_id: Mapped[object] = mapped_column(Uuid(as_uuid=True), nullable=False)
    dependency_type: Mapped[str] = mapped_column(String(48), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)

class ChangeImpactReport(Base):
    __tablename__ = "change_impact_reports"
    __table_args__ = (
        Index("ix_change_impact_project_created", "project_id", "created_at"),
        ForeignKeyConstraint(["project_id", "source_entity_id"], ["entities.project_id", "entities.id"], ondelete="RESTRICT", name="fk_change_impact_source_entity"),
        ForeignKeyConstraint(["project_id", "source_entity_id", "source_version_id"], ["entity_versions.project_id", "entity_versions.entity_id", "entity_versions.id"], ondelete="RESTRICT", name="fk_change_impact_source_version"),
    )
    id: Mapped[object] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid7)
    project_id: Mapped[object] = mapped_column(Uuid(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    source_entity_id: Mapped[object] = mapped_column(Uuid(as_uuid=True), nullable=False)
    source_version_id: Mapped[object] = mapped_column(Uuid(as_uuid=True), nullable=False)
    impact_graph: Mapped[dict] = mapped_column(JSON, nullable=False)
    recommendation: Mapped[str | None] = mapped_column(Text)
    human_decision: Mapped[str | None] = mapped_column(String(32))
    decided_by: Mapped[object | None] = mapped_column(Uuid(as_uuid=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)


class MediaObject(Base):
    """Physical object-store record. Shared by asset versions; never delete while referenced."""
    __tablename__ = "media_objects"
    __table_args__ = (
        UniqueConstraint("storage_provider", "bucket", "storage_key", name="uq_media_objects_storage_locator"),
        CheckConstraint("byte_size >= 0", name="media_object_byte_size_nonnegative"),
        CheckConstraint("length(sha256) = 64", name="media_object_sha256_length"),
        CheckConstraint("object_state IN ('staged', 'available', 'delete_pending', 'deleted', 'failed')", name="media_object_state_valid"),
        Index("ix_media_objects_sha_size", "sha256", "byte_size"),
    )
    id: Mapped[object] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid7)
    storage_provider: Mapped[str] = mapped_column(String(32), nullable=False)
    bucket: Mapped[str] = mapped_column(String(128), nullable=False)
    storage_key: Mapped[str] = mapped_column(String(512), nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    byte_size: Mapped[int] = mapped_column(Integer, nullable=False)
    mime_type: Mapped[str] = mapped_column(String(160), nullable=False)
    object_state: Mapped[str] = mapped_column(String(24), nullable=False, default="staged")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    last_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

class MediaAsset(Base):
    __tablename__ = "media_assets"
    __table_args__ = (
        UniqueConstraint("project_id", "id", name="uq_media_assets_project_id_id"),
        UniqueConstraint("project_id", "entity_id", name="uq_media_assets_project_entity"),
        ForeignKeyConstraint(["project_id", "entity_id"], ["entities.project_id", "entities.id"], ondelete="RESTRICT", name="fk_media_assets_entity"),
        Index("ix_media_assets_project_kind", "project_id", "asset_kind"),
    )
    id: Mapped[object] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid7)
    project_id: Mapped[object] = mapped_column(Uuid(as_uuid=True), nullable=False)
    entity_id: Mapped[object] = mapped_column(Uuid(as_uuid=True), nullable=False)
    asset_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    title: Mapped[str] = mapped_column(String(240), nullable=False)
    lifecycle_state: Mapped[str] = mapped_column(String(24), nullable=False, default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)

class MediaAssetVersion(Base):
    __tablename__ = "media_asset_versions"
    __table_args__ = (
        UniqueConstraint("project_id", "asset_id", "version_number", name="uq_media_asset_versions_number"),
        UniqueConstraint("project_id", "asset_id", "id", name="uq_media_asset_versions_project_asset_id"),
        ForeignKeyConstraint(["project_id", "asset_id"], ["media_assets.project_id", "media_assets.id"], ondelete="RESTRICT", name="fk_media_asset_versions_asset"),
        ForeignKeyConstraint(["project_id", "asset_id", "parent_version_id"], ["media_asset_versions.project_id", "media_asset_versions.asset_id", "media_asset_versions.id"], ondelete="RESTRICT", name="fk_media_asset_versions_parent_same_asset"),
        ForeignKeyConstraint(["media_object_id"], ["media_objects.id"], ondelete="RESTRICT", name="fk_media_asset_versions_object"),
        CheckConstraint("version_number > 0", name="media_asset_version_number_positive"),
        Index("ix_media_asset_versions_asset_created", "asset_id", "created_at"),
    )
    id: Mapped[object] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid7)
    project_id: Mapped[object] = mapped_column(Uuid(as_uuid=True), nullable=False)
    asset_id: Mapped[object] = mapped_column(Uuid(as_uuid=True), nullable=False)
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    media_object_id: Mapped[object] = mapped_column(Uuid(as_uuid=True), nullable=False)
    parent_version_id: Mapped[object | None] = mapped_column(Uuid(as_uuid=True))
    original_filename: Mapped[str] = mapped_column(String(512), nullable=False)
    metadata_snapshot: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_by: Mapped[object | None] = mapped_column(Uuid(as_uuid=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)

class MediaAssetPointer(Base):
    __tablename__ = "media_asset_pointers"
    __table_args__ = (
        UniqueConstraint("project_id", "asset_id", name="uq_media_asset_pointers_asset"),
        ForeignKeyConstraint(["project_id", "asset_id"], ["media_assets.project_id", "media_assets.id"], ondelete="CASCADE", name="fk_media_asset_pointers_asset"),
        ForeignKeyConstraint(["project_id", "asset_id", "working_version_id"], ["media_asset_versions.project_id", "media_asset_versions.asset_id", "media_asset_versions.id"], ondelete="RESTRICT", name="fk_media_asset_pointers_working"),
        ForeignKeyConstraint(["project_id", "asset_id", "approved_version_id"], ["media_asset_versions.project_id", "media_asset_versions.asset_id", "media_asset_versions.id"], ondelete="RESTRICT", name="fk_media_asset_pointers_approved"),
    )
    id: Mapped[object] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid7)
    project_id: Mapped[object] = mapped_column(Uuid(as_uuid=True), nullable=False)
    asset_id: Mapped[object] = mapped_column(Uuid(as_uuid=True), nullable=False)
    working_version_id: Mapped[object | None] = mapped_column(Uuid(as_uuid=True))
    approved_version_id: Mapped[object | None] = mapped_column(Uuid(as_uuid=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)

class MediaAssetRelation(Base):
    __tablename__ = "media_asset_relations"
    __table_args__ = (
        ForeignKeyConstraint(["project_id", "source_asset_id"], ["media_assets.project_id", "media_assets.id"], ondelete="CASCADE", name="fk_media_asset_relations_source"),
        ForeignKeyConstraint(["project_id", "target_asset_id"], ["media_assets.project_id", "media_assets.id"], ondelete="RESTRICT", name="fk_media_asset_relations_target"),
        UniqueConstraint("project_id", "source_asset_id", "target_asset_id", "relation_type", name="uq_media_asset_relation_edge"),
        CheckConstraint("source_asset_id <> target_asset_id", name="media_asset_relation_not_self"),
    )
    id: Mapped[object] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid7)
    project_id: Mapped[object] = mapped_column(Uuid(as_uuid=True), nullable=False)
    source_asset_id: Mapped[object] = mapped_column(Uuid(as_uuid=True), nullable=False)
    target_asset_id: Mapped[object] = mapped_column(Uuid(as_uuid=True), nullable=False)
    relation_type: Mapped[str] = mapped_column(String(48), nullable=False)
    attributes: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)

class MediaProvenance(Base):
    __tablename__ = "media_provenance"
    __table_args__ = (
        ForeignKeyConstraint(["project_id", "asset_id", "asset_version_id"], ["media_asset_versions.project_id", "media_asset_versions.asset_id", "media_asset_versions.id"], ondelete="RESTRICT", name="fk_media_provenance_asset_version"),
        Index("ix_media_provenance_version", "asset_version_id"),
    )
    id: Mapped[object] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid7)
    project_id: Mapped[object] = mapped_column(Uuid(as_uuid=True), nullable=False)
    asset_id: Mapped[object] = mapped_column(Uuid(as_uuid=True), nullable=False)
    asset_version_id: Mapped[object] = mapped_column(Uuid(as_uuid=True), nullable=False)
    producer_kind: Mapped[str] = mapped_column(String(24), nullable=False)
    producer_id: Mapped[object | None] = mapped_column(Uuid(as_uuid=True))
    execution_snapshot: Mapped[dict] = mapped_column(JSON, nullable=False)
    input_asset_versions: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    parameters: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)

class MediaProcessingJob(Base):
    __tablename__ = "media_processing_jobs"
    __table_args__ = (
        UniqueConstraint("project_id", "idempotency_key", name="uq_media_processing_jobs_idempotency"),
        ForeignKeyConstraint(["project_id", "asset_id", "asset_version_id"], ["media_asset_versions.project_id", "media_asset_versions.asset_id", "media_asset_versions.id"], ondelete="RESTRICT", name="fk_media_processing_jobs_asset_version"),
        CheckConstraint("attempt_count >= 0", name="media_processing_attempt_nonnegative"),
        CheckConstraint("(asset_id IS NULL AND asset_version_id IS NULL) OR (asset_id IS NOT NULL AND asset_version_id IS NOT NULL)", name="media_processing_asset_version_pair"),
        CheckConstraint("status IN ('queued', 'running', 'succeeded', 'failed', 'cancelled')", name="media_processing_status_valid"),
        Index("ix_media_processing_jobs_status_created", "status", "created_at"),
    )
    id: Mapped[object] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid7)
    project_id: Mapped[object] = mapped_column(Uuid(as_uuid=True), nullable=False)
    asset_id: Mapped[object | None] = mapped_column(Uuid(as_uuid=True))
    asset_version_id: Mapped[object | None] = mapped_column(Uuid(as_uuid=True))
    job_type: Mapped[str] = mapped_column(String(48), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="queued")
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    request_snapshot: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    result_snapshot: Mapped[dict | None] = mapped_column(JSON)
    error_detail: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)

class MediaQCRecord(Base):
    __tablename__ = "media_qc_records"
    __table_args__ = (
        ForeignKeyConstraint(["project_id", "asset_id", "asset_version_id"], ["media_asset_versions.project_id", "media_asset_versions.asset_id", "media_asset_versions.id"], ondelete="RESTRICT", name="fk_media_qc_asset_version"),
        Index("ix_media_qc_version_type_created", "asset_version_id", "qc_type", "created_at"),
        CheckConstraint("qc_type IN ('technical', 'artistic')", name="media_qc_type_valid"),
        CheckConstraint("status IN ('pass', 'warning', 'fail', 'incomplete')", name="media_qc_status_valid"),
    )
    id: Mapped[object] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid7)
    project_id: Mapped[object] = mapped_column(Uuid(as_uuid=True), nullable=False)
    asset_id: Mapped[object] = mapped_column(Uuid(as_uuid=True), nullable=False)
    asset_version_id: Mapped[object] = mapped_column(Uuid(as_uuid=True), nullable=False)
    qc_type: Mapped[str] = mapped_column(String(24), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    findings: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    tool_snapshot: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)


class Agent(Base):
    __tablename__ = "agents"
    id: Mapped[object] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid7)
    code: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    display_name: Mapped[str] = mapped_column(String(160), nullable=False)
    lifecycle_state: Mapped[str] = mapped_column(String(24), nullable=False, default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)

class AgentVersion(Base):
    __tablename__ = "agent_versions"
    __table_args__ = (
        UniqueConstraint("agent_id", "version_number", name="uq_agent_versions_number"),
        UniqueConstraint("agent_id", "id", name="uq_agent_versions_agent_id"),
        CheckConstraint("version_number > 0", name="agent_version_number_positive"),
    )
    id: Mapped[object] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid7)
    agent_id: Mapped[object] = mapped_column(Uuid(as_uuid=True), ForeignKey("agents.id", ondelete="RESTRICT"), nullable=False)
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    definition_snapshot: Mapped[dict] = mapped_column(JSON, nullable=False)
    definition_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    created_by: Mapped[object | None] = mapped_column(Uuid(as_uuid=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)

class AgentVersionPointer(Base):
    __tablename__ = "agent_version_pointers"
    __table_args__ = (UniqueConstraint("agent_id", name="uq_agent_version_pointers_agent"), ForeignKeyConstraint(["agent_id", "active_version_id"], ["agent_versions.agent_id", "agent_versions.id"], ondelete="RESTRICT", name="fk_agent_version_pointers_active"))
    id: Mapped[object] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid7)
    agent_id: Mapped[object] = mapped_column(Uuid(as_uuid=True), ForeignKey("agents.id", ondelete="CASCADE"), nullable=False)
    active_version_id: Mapped[object | None] = mapped_column(Uuid(as_uuid=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)

class Skill(Base):
    __tablename__ = "skills"
    id: Mapped[object] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid7)
    code: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    display_name: Mapped[str] = mapped_column(String(160), nullable=False)
    lifecycle_state: Mapped[str] = mapped_column(String(24), nullable=False, default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)

class SkillVersion(Base):
    __tablename__ = "skill_versions"
    __table_args__ = (
        UniqueConstraint("skill_id", "version_number", name="uq_skill_versions_number"),
        UniqueConstraint("skill_id", "id", name="uq_skill_versions_skill_id"),
        CheckConstraint("version_number > 0", name="skill_version_number_positive"),
    )
    id: Mapped[object] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid7)
    skill_id: Mapped[object] = mapped_column(Uuid(as_uuid=True), ForeignKey("skills.id", ondelete="RESTRICT"), nullable=False)
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    definition_snapshot: Mapped[dict] = mapped_column(JSON, nullable=False)
    definition_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)

class SkillVersionPointer(Base):
    __tablename__ = "skill_version_pointers"
    __table_args__ = (UniqueConstraint("skill_id", name="uq_skill_version_pointers_skill"), ForeignKeyConstraint(["skill_id", "active_version_id"], ["skill_versions.skill_id", "skill_versions.id"], ondelete="RESTRICT", name="fk_skill_version_pointers_active"))
    id: Mapped[object] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid7)
    skill_id: Mapped[object] = mapped_column(Uuid(as_uuid=True), ForeignKey("skills.id", ondelete="CASCADE"), nullable=False)
    active_version_id: Mapped[object | None] = mapped_column(Uuid(as_uuid=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)

class AgentSkillBinding(Base):
    __tablename__ = "agent_skill_bindings"
    __table_args__ = (UniqueConstraint("agent_version_id", "skill_version_id", name="uq_agent_skill_binding"),)
    id: Mapped[object] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid7)
    agent_version_id: Mapped[object] = mapped_column(Uuid(as_uuid=True), ForeignKey("agent_versions.id", ondelete="CASCADE"), nullable=False)
    skill_version_id: Mapped[object] = mapped_column(Uuid(as_uuid=True), ForeignKey("skill_versions.id", ondelete="RESTRICT"), nullable=False)
    binding_config: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)

class ModelProvider(Base):
    __tablename__ = "model_providers"
    id: Mapped[object] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid7)
    code: Mapped[str] = mapped_column(String(48), unique=True, nullable=False)
    display_name: Mapped[str] = mapped_column(String(160), nullable=False)
    lifecycle_state: Mapped[str] = mapped_column(String(24), nullable=False, default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)

class Model(Base):
    __tablename__ = "models"
    id: Mapped[object] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid7)
    model_key: Mapped[str] = mapped_column(String(96), unique=True, nullable=False)
    modality: Mapped[str] = mapped_column(String(32), nullable=False)
    capabilities: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    lifecycle_state: Mapped[str] = mapped_column(String(24), nullable=False, default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)

class ModelProviderDeployment(Base):
    __tablename__ = "model_provider_deployments"
    __table_args__ = (
        UniqueConstraint("model_id", "id", name="uq_model_provider_deployments_model_id"),
        UniqueConstraint("provider_id", "deployment_key", name="uq_model_provider_deployment_key"),
    )
    id: Mapped[object] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid7)
    provider_id: Mapped[object] = mapped_column(Uuid(as_uuid=True), ForeignKey("model_providers.id", ondelete="RESTRICT"), nullable=False)
    model_id: Mapped[object] = mapped_column(Uuid(as_uuid=True), ForeignKey("models.id", ondelete="RESTRICT"), nullable=False)
    deployment_key: Mapped[str] = mapped_column(String(128), nullable=False)
    region: Mapped[str | None] = mapped_column(String(64))
    credential_ref: Mapped[str | None] = mapped_column(String(256))
    config_snapshot: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    lifecycle_state: Mapped[str] = mapped_column(String(24), nullable=False, default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)

class AgentModelBinding(Base):
    __tablename__ = "agent_model_bindings"
    __table_args__ = (
        UniqueConstraint("agent_version_id", "purpose", "priority", name="uq_agent_model_binding_priority"),
        CheckConstraint("priority >= 0", name="agent_model_binding_priority_nonnegative"),
    )
    id: Mapped[object] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid7)
    agent_version_id: Mapped[object] = mapped_column(Uuid(as_uuid=True), ForeignKey("agent_versions.id", ondelete="CASCADE"), nullable=False)
    model_id: Mapped[object] = mapped_column(Uuid(as_uuid=True), nullable=False)
    deployment_id: Mapped[object] = mapped_column(Uuid(as_uuid=True), nullable=False)
    purpose: Mapped[str] = mapped_column(String(48), nullable=False)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    binding_config: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    __table_args__ = (
        UniqueConstraint("agent_version_id", "purpose", "priority", name="uq_agent_model_binding_priority"),
        CheckConstraint("priority >= 0", name="agent_model_binding_priority_nonnegative"),
        ForeignKeyConstraint(["model_id", "deployment_id"], ["model_provider_deployments.model_id", "model_provider_deployments.id"], ondelete="RESTRICT", name="fk_agent_model_binding_deployment"),
    )

class Task(Base):
    __tablename__ = "tasks"
    __table_args__ = (
        UniqueConstraint("project_id", "id", name="uq_tasks_project_id_id"),
        UniqueConstraint("project_id", "idempotency_key", name="uq_tasks_project_idempotency"),
        Index("ix_tasks_project_status_created", "project_id", "status", "created_at"),
        CheckConstraint("attempt_count >= 0 AND max_attempts > 0 AND attempt_count <= max_attempts", name="task_attempt_bounds"),
        CheckConstraint("status IN ('queued', 'running', 'retry_wait', 'succeeded', 'failed', 'cancelled')", name="task_status_valid"),
    )
    id: Mapped[object] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid7)
    project_id: Mapped[object] = mapped_column(Uuid(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    task_type: Mapped[str] = mapped_column(String(64), nullable=False)
    title: Mapped[str] = mapped_column(String(240), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="queued")
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=50)
    input_snapshot: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    output_snapshot: Mapped[dict | None] = mapped_column(JSON)
    idempotency_key: Mapped[str | None] = mapped_column(String(160))
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    lease_owner: Mapped[str | None] = mapped_column(String(128))
    lease_token: Mapped[str | None] = mapped_column(String(36))
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    retry_after: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancel_requested: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_detail: Mapped[dict | None] = mapped_column(JSON)
    created_by: Mapped[object | None] = mapped_column(Uuid(as_uuid=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)

class TaskDependency(Base):
    __tablename__ = "task_dependencies"
    __table_args__ = (
        ForeignKeyConstraint(["project_id", "task_id"], ["tasks.project_id", "tasks.id"], ondelete="CASCADE", name="fk_task_dependencies_task"),
        ForeignKeyConstraint(["project_id", "depends_on_task_id"], ["tasks.project_id", "tasks.id"], ondelete="RESTRICT", name="fk_task_dependencies_parent"),
        UniqueConstraint("project_id", "task_id", "depends_on_task_id", name="uq_task_dependency_edge"),
        CheckConstraint("task_id <> depends_on_task_id", name="task_dependency_not_self"),
    )
    id: Mapped[object] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid7)
    project_id: Mapped[object] = mapped_column(Uuid(as_uuid=True), nullable=False)
    task_id: Mapped[object] = mapped_column(Uuid(as_uuid=True), nullable=False)
    depends_on_task_id: Mapped[object] = mapped_column(Uuid(as_uuid=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)

class AgentRun(Base):
    __tablename__ = "agent_runs"
    __table_args__ = (
        ForeignKeyConstraint(["project_id", "task_id"], ["tasks.project_id", "tasks.id"], ondelete="RESTRICT", name="fk_agent_runs_task"),
        ForeignKeyConstraint(["agent_id", "agent_version_id"], ["agent_versions.agent_id", "agent_versions.id"], ondelete="RESTRICT", name="fk_agent_runs_agent_version"),
        UniqueConstraint("project_id", "id", name="uq_agent_runs_project_id_id"),
        Index("ix_agent_runs_project_status_created", "project_id", "status", "created_at"),
    )
    id: Mapped[object] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid7)
    project_id: Mapped[object] = mapped_column(Uuid(as_uuid=True), nullable=False)
    task_id: Mapped[object] = mapped_column(Uuid(as_uuid=True), nullable=False)
    agent_id: Mapped[object] = mapped_column(Uuid(as_uuid=True), nullable=False)
    agent_version_id: Mapped[object] = mapped_column(Uuid(as_uuid=True), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="queued")
    input_snapshot: Mapped[dict] = mapped_column(JSON, nullable=False)
    output_snapshot: Mapped[dict | None] = mapped_column(JSON)
    error_detail: Mapped[dict | None] = mapped_column(JSON)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)

class SkillRun(Base):
    __tablename__ = "skill_runs"
    __table_args__ = (
        ForeignKeyConstraint(["project_id", "agent_run_id"], ["agent_runs.project_id", "agent_runs.id"], ondelete="CASCADE", name="fk_skill_runs_agent_run"),
        ForeignKeyConstraint(["skill_id", "skill_version_id"], ["skill_versions.skill_id", "skill_versions.id"], ondelete="RESTRICT", name="fk_skill_runs_skill_version"),
        UniqueConstraint("project_id", "id", name="uq_skill_runs_project_id_id"),
        Index("ix_skill_runs_agent_run", "agent_run_id"),
    )
    id: Mapped[object] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid7)
    project_id: Mapped[object] = mapped_column(Uuid(as_uuid=True), nullable=False)
    agent_run_id: Mapped[object] = mapped_column(Uuid(as_uuid=True), nullable=False)
    skill_id: Mapped[object] = mapped_column(Uuid(as_uuid=True), nullable=False)
    skill_version_id: Mapped[object] = mapped_column(Uuid(as_uuid=True), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="queued")
    input_snapshot: Mapped[dict] = mapped_column(JSON, nullable=False)
    output_snapshot: Mapped[dict | None] = mapped_column(JSON)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)

class ModelRun(Base):
    __tablename__ = "model_runs"
    __table_args__ = (
        ForeignKeyConstraint(["project_id", "agent_run_id"], ["agent_runs.project_id", "agent_runs.id"], ondelete="CASCADE", name="fk_model_runs_agent_run"),
        ForeignKeyConstraint(["project_id", "skill_run_id"], ["skill_runs.project_id", "skill_runs.id"], ondelete="RESTRICT", name="fk_model_runs_skill_run"),
        ForeignKeyConstraint(["model_id", "deployment_id"], ["model_provider_deployments.model_id", "model_provider_deployments.id"], ondelete="RESTRICT", name="fk_model_runs_deployment"),
        UniqueConstraint("project_id", "id", name="uq_model_runs_project_id_id"),
        Index("ix_model_runs_agent_run", "agent_run_id"),
    )
    id: Mapped[object] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid7)
    project_id: Mapped[object] = mapped_column(Uuid(as_uuid=True), nullable=False)
    agent_run_id: Mapped[object] = mapped_column(Uuid(as_uuid=True), nullable=False)
    skill_run_id: Mapped[object | None] = mapped_column(Uuid(as_uuid=True))
    model_id: Mapped[object] = mapped_column(Uuid(as_uuid=True), nullable=False)
    deployment_id: Mapped[object] = mapped_column(Uuid(as_uuid=True), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="queued")
    request_snapshot: Mapped[dict] = mapped_column(JSON, nullable=False)
    response_snapshot: Mapped[dict | None] = mapped_column(JSON)
    provider_request_id: Mapped[str | None] = mapped_column(String(160))
    usage_snapshot: Mapped[dict | None] = mapped_column(JSON)
    cost_amount: Mapped[str | None] = mapped_column(String(48))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)

class RunArtifact(Base):
    __tablename__ = "run_artifacts"
    __table_args__ = (
        CheckConstraint("(CASE WHEN agent_run_id IS NULL THEN 0 ELSE 1 END + CASE WHEN skill_run_id IS NULL THEN 0 ELSE 1 END + CASE WHEN model_run_id IS NULL THEN 0 ELSE 1 END) = 1", name="run_artifact_exactly_one_owner"),
        CheckConstraint("(media_asset_id IS NULL AND media_asset_version_id IS NULL) OR (media_asset_id IS NOT NULL AND media_asset_version_id IS NOT NULL)", name="run_artifact_media_version_pair"),
        ForeignKeyConstraint(["project_id", "agent_run_id"], ["agent_runs.project_id", "agent_runs.id"], ondelete="CASCADE", name="fk_run_artifacts_agent_run"),
        ForeignKeyConstraint(["project_id", "skill_run_id"], ["skill_runs.project_id", "skill_runs.id"], ondelete="CASCADE", name="fk_run_artifacts_skill_run"),
        ForeignKeyConstraint(["project_id", "model_run_id"], ["model_runs.project_id", "model_runs.id"], ondelete="CASCADE", name="fk_run_artifacts_model_run"),
        ForeignKeyConstraint(["project_id", "media_asset_id", "media_asset_version_id"], ["media_asset_versions.project_id", "media_asset_versions.asset_id", "media_asset_versions.id"], ondelete="RESTRICT", name="fk_run_artifacts_media_version"),
    )
    id: Mapped[object] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid7)
    project_id: Mapped[object] = mapped_column(Uuid(as_uuid=True), nullable=False)
    agent_run_id: Mapped[object | None] = mapped_column(Uuid(as_uuid=True))
    skill_run_id: Mapped[object | None] = mapped_column(Uuid(as_uuid=True))
    model_run_id: Mapped[object | None] = mapped_column(Uuid(as_uuid=True))
    media_asset_id: Mapped[object | None] = mapped_column(Uuid(as_uuid=True))
    media_asset_version_id: Mapped[object | None] = mapped_column(Uuid(as_uuid=True))
    artifact_role: Mapped[str] = mapped_column(String(48), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)

class OrchestrationPlan(Base):
    __tablename__ = "orchestration_plans"
    __table_args__ = (UniqueConstraint("project_id", "id", name="uq_orchestration_plans_project_id_id"), ForeignKeyConstraint(["project_id", "task_id"], ["tasks.project_id", "tasks.id"], ondelete="CASCADE", name="fk_orchestration_plans_task"))
    id: Mapped[object] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid7)
    project_id: Mapped[object] = mapped_column(Uuid(as_uuid=True), nullable=False)
    task_id: Mapped[object] = mapped_column(Uuid(as_uuid=True), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="draft")
    approval_status: Mapped[str] = mapped_column(String(24), nullable=False, default="pending")
    approved_by: Mapped[object | None] = mapped_column(Uuid(as_uuid=True))
    approval_decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    approval_note: Mapped[str | None] = mapped_column(Text)
    plan_sha256: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    plan_snapshot: Mapped[dict] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)

class OrchestrationPlanStep(Base):
    __tablename__ = "orchestration_plan_steps"
    __table_args__ = (
        UniqueConstraint("plan_id", "step_order", name="uq_orchestration_plan_steps_order"),
        UniqueConstraint("task_id", name="uq_orchestration_plan_step_task"),
        Index("ix_orchestration_plan_steps_plan_key", "plan_id", "step_key", unique=True),
        CheckConstraint("step_order > 0", name="orchestration_plan_step_order_positive"),
        CheckConstraint("(agent_version_id IS NOT NULL AND skill_version_id IS NULL) OR (agent_version_id IS NULL AND skill_version_id IS NOT NULL)", name="orchestration_plan_step_exactly_one_capability"),
    )
    id: Mapped[object] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid7)
    plan_id: Mapped[object] = mapped_column(Uuid(as_uuid=True), ForeignKey("orchestration_plans.id", ondelete="CASCADE"), nullable=False)
    step_order: Mapped[int] = mapped_column(Integer, nullable=False)
    agent_version_id: Mapped[object | None] = mapped_column(Uuid(as_uuid=True), ForeignKey("agent_versions.id", ondelete="RESTRICT"))
    skill_version_id: Mapped[object | None] = mapped_column(Uuid(as_uuid=True), ForeignKey("skill_versions.id", ondelete="RESTRICT"))
    step_key: Mapped[str | None] = mapped_column(String(96))
    task_id: Mapped[object | None] = mapped_column(Uuid(as_uuid=True), ForeignKey("tasks.id", ondelete="RESTRICT"))
    step_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    input_snapshot: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    depends_on_step_keys: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    output_snapshot: Mapped[dict | None] = mapped_column(JSON)
    error_detail: Mapped[dict | None] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="pending")
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

class DirectorDecisionCase(Base):
    """Version-pinned Executive Director recommendation awaiting human disposition."""
    __tablename__ = "director_decision_cases"
    __table_args__ = (
        UniqueConstraint("project_id", "case_key", name="uq_director_decision_cases_project_key"),
        CheckConstraint("status IN ('open', 'approved', 'rejected', 'deferred', 'closed')", name="director_decision_case_status_valid"),
        CheckConstraint("decision IS NULL OR decision IN ('approved', 'rejected', 'deferred', 'closed')", name="director_decision_case_decision_valid"),
        CheckConstraint("(status = 'open' AND decision IS NULL AND decided_by IS NULL AND decided_at IS NULL) OR (status <> 'open' AND decision = status AND decided_by IS NOT NULL AND decided_at IS NOT NULL)", name="director_decision_case_decision_consistent"),
        CheckConstraint("severity IN ('critical', 'high', 'medium', 'low', 'info')", name="director_decision_case_severity_valid"),
        Index("ix_director_decision_cases_project_status", "project_id", "status", "created_at"),
    )
    id: Mapped[object] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid7)
    project_id: Mapped[object] = mapped_column(Uuid(as_uuid=True), ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False)
    case_key: Mapped[str] = mapped_column(String(64), nullable=False)
    source_brief_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    source_state_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    recommendation_code: Mapped[str] = mapped_column(String(64), nullable=False)
    severity: Mapped[str] = mapped_column(String(16), nullable=False)
    approval_required: Mapped[str] = mapped_column(String(24), nullable=False)
    evidence_refs: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    proposal_snapshot: Mapped[dict] = mapped_column(JSON, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="open")
    decision: Mapped[str | None] = mapped_column(String(16))
    decided_by: Mapped[object | None] = mapped_column(Uuid(as_uuid=True))
    decision_note: Mapped[str | None] = mapped_column(Text)
    authorized_action_snapshot: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ActionExecution(Base):
    """One-time, approval-bound execution record for a director decision case."""
    __tablename__ = "action_executions"
    __table_args__ = (
        UniqueConstraint("project_id", "idempotency_key", name="uq_action_executions_project_idempotency"),
        UniqueConstraint("decision_case_id", name="uq_action_executions_decision_case"),
        CheckConstraint("status IN ('succeeded')", name="action_execution_status_valid"),
        Index("ix_action_executions_project_created", "project_id", "created_at"),
    )
    id: Mapped[object] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid7)
    project_id: Mapped[object] = mapped_column(Uuid(as_uuid=True), ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False)
    decision_case_id: Mapped[object] = mapped_column(Uuid(as_uuid=True), ForeignKey("director_decision_cases.id", ondelete="RESTRICT"), nullable=False)
    action_type: Mapped[str] = mapped_column(String(48), nullable=False)
    action_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(160), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="succeeded")
    requested_by: Mapped[object] = mapped_column(Uuid(as_uuid=True), ForeignKey("principals.id", ondelete="RESTRICT"), nullable=False)
    result_snapshot: Mapped[dict] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)


class AgentEvaluation(Base):
    """Immutable specialist review of an AgentRun output."""
    __tablename__ = "agent_evaluations"
    __table_args__ = (
        ForeignKeyConstraint(["project_id", "agent_run_id"], ["agent_runs.project_id", "agent_runs.id"], ondelete="RESTRICT", name="fk_agent_evaluations_agent_run"),
        ForeignKeyConstraint(["project_id", "task_id"], ["tasks.project_id", "tasks.id"], ondelete="RESTRICT", name="fk_agent_evaluations_task"),
        ForeignKeyConstraint(["project_id", "rework_task_id"], ["tasks.project_id", "tasks.id"], ondelete="RESTRICT", name="fk_agent_evaluations_rework_task_project"),
        UniqueConstraint("project_id", "idempotency_key", name="uq_agent_evaluations_idempotency"),
        UniqueConstraint("rework_task_id", name="uq_agent_evaluations_rework_task"),
        CheckConstraint("score >= 0 AND score <= 1", name="agent_evaluation_score_range"),
        CheckConstraint("decision IN ('accepted', 'rework', 'escalate')", name="agent_evaluation_decision_valid"),
        CheckConstraint("rework_round >= 0", name="agent_evaluation_rework_round_nonnegative"),
        Index("ix_agent_evaluations_run_created", "agent_run_id", "created_at"),
    )
    id: Mapped[object] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid7)
    project_id: Mapped[object] = mapped_column(Uuid(as_uuid=True), nullable=False)
    task_id: Mapped[object] = mapped_column(Uuid(as_uuid=True), nullable=False)
    agent_run_id: Mapped[object] = mapped_column(Uuid(as_uuid=True), nullable=False)
    reviewer_agent_version_id: Mapped[object] = mapped_column(Uuid(as_uuid=True), ForeignKey("agent_versions.id", ondelete="RESTRICT"), nullable=False)
    decision: Mapped[str] = mapped_column(String(24), nullable=False)
    score: Mapped[float] = mapped_column(Float, nullable=False)
    rework_round: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    rubric_snapshot: Mapped[dict] = mapped_column(JSON, nullable=False)
    findings: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    required_changes: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    idempotency_key: Mapped[str] = mapped_column(String(160), nullable=False)
    rework_task_id: Mapped[object | None] = mapped_column(Uuid(as_uuid=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)


class AgentMessage(Base):
    __tablename__ = "agent_messages"
    __table_args__ = (
        ForeignKeyConstraint(["project_id", "task_id"], ["tasks.project_id", "tasks.id"], ondelete="CASCADE", name="fk_agent_messages_task"),
        UniqueConstraint("project_id", "idempotency_key", name="uq_agent_messages_idempotency"),
        Index("ix_agent_messages_project_created", "project_id", "created_at"),
    )
    id: Mapped[object] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid7)
    project_id: Mapped[object] = mapped_column(Uuid(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    task_id: Mapped[object | None] = mapped_column(Uuid(as_uuid=True))
    from_agent_id: Mapped[object] = mapped_column(Uuid(as_uuid=True), ForeignKey("agents.id", ondelete="RESTRICT"), nullable=False)
    to_agent_id: Mapped[object | None] = mapped_column(Uuid(as_uuid=True), ForeignKey("agents.id", ondelete="RESTRICT"))
    message_type: Mapped[str] = mapped_column(String(48), nullable=False)
    correlation_id: Mapped[object | None] = mapped_column(Uuid(as_uuid=True))
    payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    idempotency_key: Mapped[str | None] = mapped_column(String(160))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)

class RunEvent(Base):
    __tablename__ = "run_events"
    __table_args__ = (
        ForeignKeyConstraint(["project_id", "agent_run_id"], ["agent_runs.project_id", "agent_runs.id"], ondelete="CASCADE", name="fk_run_events_agent_run"),
        Index("ix_run_events_agent_run_created", "agent_run_id", "created_at"),
    )
    id: Mapped[object] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid7)
    project_id: Mapped[object] = mapped_column(Uuid(as_uuid=True), nullable=False)
    agent_run_id: Mapped[object] = mapped_column(Uuid(as_uuid=True), nullable=False)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)

class OutboxEvent(Base):
    __tablename__ = "outbox_events"
    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_outbox_events_idempotency"),
        Index("ix_outbox_events_status_created", "status", "created_at"),
        CheckConstraint("attempt_count >= 0 AND max_attempts > 0", name="outbox_attempt_bounds"),
        CheckConstraint("status IN ('pending', 'publishing', 'published', 'dead')", name="outbox_status_valid"),
    )
    id: Mapped[object] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid7)
    aggregate_type: Mapped[str] = mapped_column(String(48), nullable=False)
    aggregate_id: Mapped[object] = mapped_column(Uuid(as_uuid=True), nullable=False)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(160), nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="pending")
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=8)
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    claimed_by: Mapped[str | None] = mapped_column(String(128))
    claim_token: Mapped[str | None] = mapped_column(String(36))
    claim_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

class WorkerInstance(Base):
    __tablename__ = "worker_instances"
    __table_args__ = (
        UniqueConstraint("worker_id", name="uq_worker_instances_worker_id"),
        Index("ix_worker_instances_status_heartbeat", "status", "last_heartbeat_at"),
        CheckConstraint("status IN ('starting', 'online', 'stopping', 'offline', 'stale')", name="worker_instance_status_valid"),
    )
    id: Mapped[object] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid7)
    worker_id: Mapped[str] = mapped_column(String(128), nullable=False)
    instance_token: Mapped[str] = mapped_column(String(36), nullable=False, default="legacy")
    process_id: Mapped[int | None] = mapped_column(Integer)
    host_name: Mapped[str | None] = mapped_column(String(160))
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="starting")
    capabilities: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    metadata_snapshot: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    last_heartbeat_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    stopped_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class TaskDeadLetter(Base):
    __tablename__ = "task_dead_letters"
    __table_args__ = (
        UniqueConstraint("task_id", name="uq_task_dead_letters_task"),
        Index("ix_task_dead_letters_created", "created_at"),
        ForeignKeyConstraint(["project_id", "task_id"], ["tasks.project_id", "tasks.id"], ondelete="RESTRICT", name="fk_task_dead_letters_task"),
    )
    id: Mapped[object] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid7)
    project_id: Mapped[object] = mapped_column(Uuid(as_uuid=True), nullable=False)
    task_id: Mapped[object] = mapped_column(Uuid(as_uuid=True), nullable=False)
    task_type: Mapped[str] = mapped_column(String(64), nullable=False)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False)
    input_snapshot: Mapped[dict] = mapped_column(JSON, nullable=False)
    error_detail: Mapped[dict] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolution_note: Mapped[str | None] = mapped_column(Text)


class InboxEvent(Base):
    __tablename__ = "inbox_events"
    __table_args__ = (UniqueConstraint("consumer_key", "idempotency_key", name="uq_inbox_events_consumer_idempotency"),)
    id: Mapped[object] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid7)
    consumer_key: Mapped[str] = mapped_column(String(96), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(160), nullable=False)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="received")
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class IntegrationSource(Base):
    __tablename__ = "integration_sources"
    __table_args__ = (
        UniqueConstraint("project_id", "code", name="uq_integration_sources_project_code"),
        UniqueConstraint("project_id", "id", name="uq_integration_sources_project_id"),
        ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE", name="fk_integration_sources_project"),
    )
    id: Mapped[object] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid7)
    project_id: Mapped[object] = mapped_column(Uuid(as_uuid=True), nullable=False)
    code: Mapped[str] = mapped_column(String(64), nullable=False)
    source_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    display_name: Mapped[str] = mapped_column(String(160), nullable=False)
    source_version: Mapped[str | None] = mapped_column(String(64))
    source_sha256: Mapped[str | None] = mapped_column(String(64))
    config_snapshot: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    lifecycle_state: Mapped[str] = mapped_column(String(24), nullable=False, default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)

class IntegrationRun(Base):
    __tablename__ = "integration_runs"
    __table_args__ = (
        UniqueConstraint("project_id", "id", name="uq_integration_runs_project_id"),
        UniqueConstraint("integration_source_id", "idempotency_key", name="uq_integration_runs_idempotency"),
        ForeignKeyConstraint(["project_id", "integration_source_id"], ["integration_sources.project_id", "integration_sources.id"], ondelete="RESTRICT", name="fk_integration_runs_source"),
        Index("ix_integration_runs_project_status_created", "project_id", "status", "created_at"),
    )
    id: Mapped[object] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid7)
    project_id: Mapped[object] = mapped_column(Uuid(as_uuid=True), nullable=False)
    integration_source_id: Mapped[object] = mapped_column(Uuid(as_uuid=True), nullable=False)
    run_type: Mapped[str] = mapped_column(String(24), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="queued")
    idempotency_key: Mapped[str] = mapped_column(String(160), nullable=False)
    package_version: Mapped[str | None] = mapped_column(String(64))
    package_sha256: Mapped[str | None] = mapped_column(String(64))
    command_snapshot: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    input_snapshot: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    output_snapshot: Mapped[dict | None] = mapped_column(JSON)
    validation_snapshot: Mapped[dict | None] = mapped_column(JSON)
    exit_code: Mapped[int | None] = mapped_column(Integer)
    error_detail: Mapped[dict | None] = mapped_column(JSON)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)

class IntegrationObjectMapping(Base):
    __tablename__ = "integration_object_mappings"
    __table_args__ = (
        ForeignKeyConstraint(["project_id", "integration_source_id"], ["integration_sources.project_id", "integration_sources.id"], ondelete="CASCADE", name="fk_integration_object_mappings_source"),
        ForeignKeyConstraint(["project_id", "canonical_entity_id"], ["entities.project_id", "entities.id"], ondelete="RESTRICT", name="fk_integration_object_mappings_entity"),
        UniqueConstraint("integration_source_id", "source_object_type", "source_object_key", name="uq_integration_object_mapping_source_key"),
        CheckConstraint("mapping_state IN ('unmapped', 'mapped', 'conflict', 'retired')", name="integration_mapping_state_valid"),
        CheckConstraint("(mapping_state = 'mapped' AND canonical_entity_id IS NOT NULL) OR (mapping_state <> 'mapped' AND canonical_entity_id IS NULL)", name="integration_mapping_entity_state_consistency"),
    )
    id: Mapped[object] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid7)
    project_id: Mapped[object] = mapped_column(Uuid(as_uuid=True), nullable=False)
    integration_source_id: Mapped[object] = mapped_column(Uuid(as_uuid=True), nullable=False)
    source_object_type: Mapped[str] = mapped_column(String(48), nullable=False)
    source_object_key: Mapped[str] = mapped_column(String(256), nullable=False)
    canonical_entity_id: Mapped[object | None] = mapped_column(Uuid(as_uuid=True))
    mapping_state: Mapped[str] = mapped_column(String(24), nullable=False, default="unmapped")
    mapping_snapshot: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)

class IntegrationObjectSnapshot(Base):
    __tablename__ = "integration_object_snapshots"
    __table_args__ = (
        ForeignKeyConstraint(["project_id", "integration_run_id"], ["integration_runs.project_id", "integration_runs.id"], ondelete="CASCADE", name="fk_integration_object_snapshots_run"),
        UniqueConstraint("integration_run_id", "source_object_type", "source_object_key", name="uq_integration_object_snapshot_source_key"),
        CheckConstraint("length(raw_sha256) = 64", name="integration_snapshot_sha256_length"),
        Index("ix_integration_object_snapshots_source_key", "source_object_type", "source_object_key"),
    )
    id: Mapped[object] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid7)
    project_id: Mapped[object] = mapped_column(Uuid(as_uuid=True), nullable=False)
    integration_run_id: Mapped[object] = mapped_column(Uuid(as_uuid=True), nullable=False)
    source_object_type: Mapped[str] = mapped_column(String(48), nullable=False)
    source_object_key: Mapped[str] = mapped_column(String(256), nullable=False)
    raw_payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    raw_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    source_range_snapshot: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)

class FMSourceRange(Base):
    __tablename__ = "fm_source_ranges"
    __table_args__ = (
        ForeignKeyConstraint(["project_id", "integration_run_id"], ["integration_runs.project_id", "integration_runs.id"], ondelete="CASCADE", name="fk_fm_source_ranges_run"),
        ForeignKeyConstraint(["project_id", "canonical_entity_id"], ["entities.project_id", "entities.id"], ondelete="RESTRICT", name="fk_fm_source_ranges_entity"),
        CheckConstraint("(line_start IS NULL AND line_end IS NULL) OR (line_start > 0 AND line_end >= line_start)", name="fm_source_range_line_order"),
        CheckConstraint("(time_start_ms IS NULL AND time_end_ms IS NULL) OR (time_start_ms >= 0 AND time_end_ms >= time_start_ms)", name="fm_source_range_time_order"),
        CheckConstraint("timing_source IN ('authored', 'estimated', 'measured', 'unknown')", name="fm_source_range_timing_source_valid"),
    )
    id: Mapped[object] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid7)
    project_id: Mapped[object] = mapped_column(Uuid(as_uuid=True), nullable=False)
    integration_run_id: Mapped[object] = mapped_column(Uuid(as_uuid=True), nullable=False)
    canonical_entity_id: Mapped[object | None] = mapped_column(Uuid(as_uuid=True))
    source_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    source_object_key: Mapped[str | None] = mapped_column(String(256))
    line_start: Mapped[int | None] = mapped_column(Integer)
    line_end: Mapped[int | None] = mapped_column(Integer)
    exact_text: Mapped[str | None] = mapped_column(Text)
    time_start_ms: Mapped[int | None] = mapped_column(Integer)
    time_end_ms: Mapped[int | None] = mapped_column(Integer)
    timing_source: Mapped[str] = mapped_column(String(16), nullable=False, default="unknown")
    range_snapshot: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)

class FMPerformanceTrack(Base):
    __tablename__ = "fm_performance_tracks"
    __table_args__ = (
        ForeignKeyConstraint(["project_id", "integration_run_id"], ["integration_runs.project_id", "integration_runs.id"], ondelete="CASCADE", name="fk_fm_performance_tracks_run"),
        ForeignKeyConstraint(["project_id", "character_entity_id"], ["entities.project_id", "entities.id"], ondelete="RESTRICT", name="fk_fm_performance_tracks_character"),
        UniqueConstraint("integration_run_id", "track_key", name="uq_fm_performance_track_key"),
        CheckConstraint("track_kind IN ('character', 'group', 'environment', 'other')", name="fm_performance_track_kind_valid"),
    )
    id: Mapped[object] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid7)
    project_id: Mapped[object] = mapped_column(Uuid(as_uuid=True), nullable=False)
    integration_run_id: Mapped[object] = mapped_column(Uuid(as_uuid=True), nullable=False)
    track_key: Mapped[str] = mapped_column(String(160), nullable=False)
    track_kind: Mapped[str] = mapped_column(String(24), nullable=False)
    character_entity_id: Mapped[object | None] = mapped_column(Uuid(as_uuid=True))
    concurrency_group: Mapped[str | None] = mapped_column(String(128))
    parallel_with: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    timing_provenance: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    track_snapshot: Mapped[dict] = mapped_column(JSON, nullable=False)

class FMCoverageDecision(Base):
    __tablename__ = "fm_coverage_decisions"
    __table_args__ = (
        ForeignKeyConstraint(["project_id", "integration_run_id"], ["integration_runs.project_id", "integration_runs.id"], ondelete="CASCADE", name="fk_fm_coverage_decisions_run"),
        ForeignKeyConstraint(["project_id", "event_entity_id"], ["entities.project_id", "entities.id"], ondelete="RESTRICT", name="fk_fm_coverage_decisions_event"),
        CheckConstraint("coverage_status IN ('covered', 'partially_covered', 'not_selected')", name="fm_coverage_status_valid"),
        CheckConstraint("review_state IN ('proposed', 'under_review', 'approval_pending')", name="fm_coverage_review_state_valid"),
        CheckConstraint("confidence IS NULL OR (confidence >= 0 AND confidence <= 1)", name="fm_coverage_confidence_range"),
    )
    id: Mapped[object] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid7)
    project_id: Mapped[object] = mapped_column(Uuid(as_uuid=True), nullable=False)
    integration_run_id: Mapped[object] = mapped_column(Uuid(as_uuid=True), nullable=False)
    event_entity_id: Mapped[object | None] = mapped_column(Uuid(as_uuid=True))
    event_source_key: Mapped[str] = mapped_column(String(160), nullable=False)
    coverage_status: Mapped[str] = mapped_column(String(24), nullable=False)
    required_dimensions: Mapped[list] = mapped_column(JSON, nullable=False)
    covered_dimensions: Mapped[list] = mapped_column(JSON, nullable=False)
    selected_shot_source_keys: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    selected_shot_entity_ids: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    source_range_snapshot: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    confidence: Mapped[float | None] = mapped_column(Float)
    human_review_required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    review_state: Mapped[str] = mapped_column(String(24), nullable=False, default="proposed")
    decision_snapshot: Mapped[dict] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)

class Principal(Base):
    """Stable internal identity for a human user or non-human service account."""
    __tablename__ = "principals"
    __table_args__ = (
        CheckConstraint("principal_kind IN ('human', 'service')", name="principal_kind_valid"),
        Index("ix_principals_kind_active", "principal_kind", "is_active"),
    )
    id: Mapped[object] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid7)
    principal_kind: Mapped[str] = mapped_column(String(16), nullable=False)
    display_name: Mapped[str] = mapped_column(String(160), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)


class ApiToken(Base):
    """High-entropy opaque bearer token; only its SHA-256 digest is persisted."""
    __tablename__ = "api_tokens"
    __table_args__ = (
        CheckConstraint("length(token_hash) = 64", name="api_token_hash_length"),
        Index("ix_api_tokens_principal_active", "principal_id", "revoked_at", "expires_at"),
    )
    id: Mapped[object] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid7)
    principal_id: Mapped[object] = mapped_column(Uuid(as_uuid=True), ForeignKey("principals.id", ondelete="CASCADE"), nullable=False)
    token_prefix: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
