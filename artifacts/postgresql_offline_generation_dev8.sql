BEGIN;

CREATE TABLE alembic_version (
    version_num VARCHAR(32) NOT NULL, 
    CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num)
);

-- Running upgrade  -> 0001_core

CREATE TYPE member_role AS ENUM ('owner', 'producer', 'director', 'department_lead', 'collaborator', 'viewer');

CREATE TYPE approval_status AS ENUM ('pending', 'approved', 'rejected', 'changes_requested', 'withdrawn');

CREATE TABLE projects (
    id UUID NOT NULL, 
    code VARCHAR(32) NOT NULL, 
    name VARCHAR(200) NOT NULL, 
    description TEXT, 
    status VARCHAR(24) NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    CONSTRAINT pk_projects PRIMARY KEY (id), 
    CONSTRAINT uq_projects_code UNIQUE (code)
);

CREATE TYPE member_role AS ENUM ('owner', 'producer', 'director', 'department_lead', 'collaborator', 'viewer');

CREATE TABLE project_members (
    id UUID NOT NULL, 
    project_id UUID NOT NULL, 
    principal_id UUID NOT NULL, 
    role member_role NOT NULL, 
    is_active BOOLEAN NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    CONSTRAINT pk_project_members PRIMARY KEY (id), 
    CONSTRAINT uq_project_members_project_principal UNIQUE (project_id, principal_id), 
    CONSTRAINT fk_project_members_project_id_projects FOREIGN KEY(project_id) REFERENCES projects (id) ON DELETE CASCADE
);

CREATE TABLE entities (
    id UUID NOT NULL, 
    project_id UUID NOT NULL, 
    entity_type VARCHAR(48) NOT NULL, 
    business_code VARCHAR(48), 
    title VARCHAR(240) NOT NULL, 
    lifecycle_state VARCHAR(24) NOT NULL, 
    created_by UUID, 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    archived_at TIMESTAMP WITH TIME ZONE, 
    CONSTRAINT pk_entities PRIMARY KEY (id), 
    CONSTRAINT uq_entities_project_id_id UNIQUE (project_id, id), 
    CONSTRAINT ck_entities_ck_entities_entity_type_nonempty CHECK (length(entity_type) > 0), 
    CONSTRAINT fk_entities_project_id_projects FOREIGN KEY(project_id) REFERENCES projects (id) ON DELETE RESTRICT
);

CREATE INDEX ix_entities_project_type ON entities (project_id, entity_type);

CREATE TABLE entity_versions (
    id UUID NOT NULL, 
    project_id UUID NOT NULL, 
    entity_id UUID NOT NULL, 
    version_number INTEGER NOT NULL, 
    content JSON NOT NULL, 
    content_sha256 VARCHAR(64) NOT NULL, 
    parent_version_id UUID, 
    change_summary TEXT, 
    created_by UUID, 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    CONSTRAINT pk_entity_versions PRIMARY KEY (id), 
    CONSTRAINT fk_entity_versions_project_entity FOREIGN KEY(project_id, entity_id) REFERENCES entities (project_id, id) ON DELETE RESTRICT, 
    CONSTRAINT fk_entity_versions_parent_same_entity FOREIGN KEY(project_id, entity_id, parent_version_id) REFERENCES entity_versions (project_id, entity_id, id) ON DELETE RESTRICT, 
    CONSTRAINT uq_entity_versions_number UNIQUE (project_id, entity_id, version_number), 
    CONSTRAINT uq_entity_versions_project_entity_id UNIQUE (project_id, entity_id, id), 
    CONSTRAINT ck_entity_versions_ck_entity_versions_version_number_positive CHECK (version_number > 0)
);

CREATE INDEX ix_entity_versions_entity_created ON entity_versions (entity_id, created_at);

CREATE TABLE entity_version_pointers (
    id UUID NOT NULL, 
    project_id UUID NOT NULL, 
    entity_id UUID NOT NULL, 
    working_version_id UUID, 
    approved_version_id UUID, 
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    CONSTRAINT pk_entity_version_pointers PRIMARY KEY (id), 
    CONSTRAINT fk_version_pointers_entity FOREIGN KEY(project_id, entity_id) REFERENCES entities (project_id, id) ON DELETE CASCADE, 
    CONSTRAINT fk_version_pointers_working_version FOREIGN KEY(project_id, entity_id, working_version_id) REFERENCES entity_versions (project_id, entity_id, id) ON DELETE RESTRICT, 
    CONSTRAINT fk_version_pointers_approved_version FOREIGN KEY(project_id, entity_id, approved_version_id) REFERENCES entity_versions (project_id, entity_id, id) ON DELETE RESTRICT, 
    CONSTRAINT uq_entity_version_pointers_entity UNIQUE (project_id, entity_id)
);

CREATE TABLE entity_relations (
    id UUID NOT NULL, 
    project_id UUID NOT NULL, 
    source_entity_id UUID NOT NULL, 
    target_entity_id UUID NOT NULL, 
    relation_type VARCHAR(48) NOT NULL, 
    attributes JSON NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    CONSTRAINT pk_entity_relations PRIMARY KEY (id), 
    CONSTRAINT fk_entity_relations_source FOREIGN KEY(project_id, source_entity_id) REFERENCES entities (project_id, id) ON DELETE CASCADE, 
    CONSTRAINT fk_entity_relations_target FOREIGN KEY(project_id, target_entity_id) REFERENCES entities (project_id, id) ON DELETE RESTRICT, 
    CONSTRAINT uq_entity_relation_edge UNIQUE (project_id, source_entity_id, target_entity_id, relation_type), 
    CONSTRAINT ck_entity_relations_ck_entity_relations_relation_not_self CHECK (source_entity_id <> target_entity_id)
);

CREATE TABLE audit_logs (
    id UUID NOT NULL, 
    project_id UUID, 
    actor_id UUID, 
    actor_kind VARCHAR(24) NOT NULL, 
    action VARCHAR(64) NOT NULL, 
    object_type VARCHAR(48) NOT NULL, 
    object_id UUID, 
    details JSON NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    CONSTRAINT pk_audit_logs PRIMARY KEY (id), 
    CONSTRAINT fk_audit_logs_project_id_projects FOREIGN KEY(project_id) REFERENCES projects (id) ON DELETE RESTRICT
);

CREATE INDEX ix_audit_logs_project_created ON audit_logs (project_id, created_at);

CREATE TABLE approval_workflows (
    id UUID NOT NULL, 
    project_id UUID NOT NULL, 
    code VARCHAR(48) NOT NULL, 
    name VARCHAR(160) NOT NULL, 
    is_active BOOLEAN NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    CONSTRAINT pk_approval_workflows PRIMARY KEY (id), 
    CONSTRAINT uq_approval_workflow_project_code UNIQUE (project_id, code), 
    CONSTRAINT uq_approval_workflows_project_id UNIQUE (project_id, id), 
    CONSTRAINT fk_approval_workflows_project_id_projects FOREIGN KEY(project_id) REFERENCES projects (id) ON DELETE CASCADE
);

CREATE TABLE approval_steps (
    id UUID NOT NULL, 
    workflow_id UUID NOT NULL, 
    step_order INTEGER NOT NULL, 
    required_role VARCHAR(32) NOT NULL, 
    is_required BOOLEAN NOT NULL, 
    CONSTRAINT pk_approval_steps PRIMARY KEY (id), 
    CONSTRAINT uq_approval_steps_order UNIQUE (workflow_id, step_order), 
    CONSTRAINT ck_approval_steps_ck_approval_steps_step_order_positive CHECK (step_order > 0), 
    CONSTRAINT fk_approval_steps_workflow_id_approval_workflows FOREIGN KEY(workflow_id) REFERENCES approval_workflows (id) ON DELETE CASCADE
);

CREATE TYPE approval_status AS ENUM ('pending', 'approved', 'rejected', 'changes_requested', 'withdrawn');

CREATE TABLE approval_records (
    id UUID NOT NULL, 
    project_id UUID NOT NULL, 
    entity_id UUID NOT NULL, 
    entity_version_id UUID NOT NULL, 
    workflow_id UUID, 
    step_order INTEGER NOT NULL, 
    reviewer_id UUID NOT NULL, 
    status approval_status NOT NULL, 
    decision_note TEXT, 
    decided_at TIMESTAMP WITH TIME ZONE, 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    CONSTRAINT pk_approval_records PRIMARY KEY (id), 
    CONSTRAINT fk_approval_records_version FOREIGN KEY(project_id, entity_id, entity_version_id) REFERENCES entity_versions (project_id, entity_id, id) ON DELETE RESTRICT, 
    CONSTRAINT fk_approval_records_workflow_same_project FOREIGN KEY(project_id, workflow_id) REFERENCES approval_workflows (project_id, id) ON DELETE RESTRICT, 
    CONSTRAINT ck_approval_records_ck_approval_records_approval_record_7d46 CHECK (step_order > 0), 
    CONSTRAINT fk_approval_records_workflow_id_approval_workflows FOREIGN KEY(workflow_id) REFERENCES approval_workflows (id) ON DELETE RESTRICT
);

CREATE INDEX ix_approval_records_version_status ON approval_records (entity_version_id, status);

CREATE TABLE entity_dependencies (
    id UUID NOT NULL, 
    project_id UUID NOT NULL, 
    source_entity_id UUID NOT NULL, 
    dependent_entity_id UUID NOT NULL, 
    dependency_type VARCHAR(48) NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    CONSTRAINT pk_entity_dependencies PRIMARY KEY (id), 
    CONSTRAINT fk_entity_dependencies_source FOREIGN KEY(project_id, source_entity_id) REFERENCES entities (project_id, id) ON DELETE CASCADE, 
    CONSTRAINT fk_entity_dependencies_dependent FOREIGN KEY(project_id, dependent_entity_id) REFERENCES entities (project_id, id) ON DELETE RESTRICT, 
    CONSTRAINT uq_entity_dependency_edge UNIQUE (project_id, source_entity_id, dependent_entity_id, dependency_type), 
    CONSTRAINT ck_entity_dependencies_ck_entity_dependencies_dependenc_ce68 CHECK (source_entity_id <> dependent_entity_id)
);

CREATE TABLE change_impact_reports (
    id UUID NOT NULL, 
    project_id UUID NOT NULL, 
    source_entity_id UUID NOT NULL, 
    source_version_id UUID NOT NULL, 
    impact_graph JSON NOT NULL, 
    recommendation TEXT, 
    human_decision VARCHAR(32), 
    decided_by UUID, 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    CONSTRAINT pk_change_impact_reports PRIMARY KEY (id), 
    CONSTRAINT fk_change_impact_source_entity FOREIGN KEY(project_id, source_entity_id) REFERENCES entities (project_id, id) ON DELETE RESTRICT, 
    CONSTRAINT fk_change_impact_source_version FOREIGN KEY(project_id, source_entity_id, source_version_id) REFERENCES entity_versions (project_id, entity_id, id) ON DELETE RESTRICT, 
    CONSTRAINT fk_change_impact_reports_project_id_projects FOREIGN KEY(project_id) REFERENCES projects (id) ON DELETE CASCADE
);

CREATE INDEX ix_change_impact_project_created ON change_impact_reports (project_id, created_at);

CREATE OR REPLACE FUNCTION afs_reject_entity_version_mutation() RETURNS trigger AS $$ BEGIN RAISE EXCEPTION 'entity_versions are immutable; create a new version'; END; $$ LANGUAGE plpgsql;

CREATE TRIGGER trg_entity_versions_immutable BEFORE UPDATE OR DELETE ON entity_versions FOR EACH ROW EXECUTE FUNCTION afs_reject_entity_version_mutation();

INSERT INTO alembic_version (version_num) VALUES ('0001_core') RETURNING alembic_version.version_num;

-- Running upgrade 0001_core -> 0002_dam

CREATE TABLE media_objects (
    id UUID NOT NULL, 
    storage_provider VARCHAR(32) NOT NULL, 
    bucket VARCHAR(128) NOT NULL, 
    storage_key VARCHAR(512) NOT NULL, 
    sha256 VARCHAR(64) NOT NULL, 
    byte_size INTEGER NOT NULL, 
    mime_type VARCHAR(160) NOT NULL, 
    object_state VARCHAR(24) NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    last_verified_at TIMESTAMP WITH TIME ZONE, 
    CONSTRAINT pk_media_objects PRIMARY KEY (id), 
    CONSTRAINT uq_media_objects_storage_locator UNIQUE (storage_provider, bucket, storage_key), 
    CONSTRAINT ck_media_objects_ck_media_objects_media_object_byte_siz_7671 CHECK (byte_size >= 0), 
    CONSTRAINT ck_media_objects_ck_media_objects_media_object_sha256_length CHECK (length(sha256) = 64), 
    CONSTRAINT ck_media_objects_ck_media_objects_media_object_state_valid CHECK (object_state IN ('staged', 'available', 'delete_pending', 'deleted', 'failed'))
);

CREATE INDEX ix_media_objects_sha_size ON media_objects (sha256, byte_size);

CREATE TABLE media_assets (
    id UUID NOT NULL, 
    project_id UUID NOT NULL, 
    entity_id UUID NOT NULL, 
    asset_kind VARCHAR(32) NOT NULL, 
    title VARCHAR(240) NOT NULL, 
    lifecycle_state VARCHAR(24) NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    CONSTRAINT pk_media_assets PRIMARY KEY (id), 
    CONSTRAINT fk_media_assets_entity FOREIGN KEY(project_id, entity_id) REFERENCES entities (project_id, id) ON DELETE RESTRICT, 
    CONSTRAINT uq_media_assets_project_id_id UNIQUE (project_id, id), 
    CONSTRAINT uq_media_assets_project_entity UNIQUE (project_id, entity_id)
);

CREATE INDEX ix_media_assets_project_kind ON media_assets (project_id, asset_kind);

CREATE TABLE media_asset_versions (
    id UUID NOT NULL, 
    project_id UUID NOT NULL, 
    asset_id UUID NOT NULL, 
    version_number INTEGER NOT NULL, 
    media_object_id UUID NOT NULL, 
    parent_version_id UUID, 
    original_filename VARCHAR(512) NOT NULL, 
    metadata_snapshot JSON NOT NULL, 
    created_by UUID, 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    CONSTRAINT pk_media_asset_versions PRIMARY KEY (id), 
    CONSTRAINT fk_media_asset_versions_asset FOREIGN KEY(project_id, asset_id) REFERENCES media_assets (project_id, id) ON DELETE RESTRICT, 
    CONSTRAINT fk_media_asset_versions_parent_same_asset FOREIGN KEY(project_id, asset_id, parent_version_id) REFERENCES media_asset_versions (project_id, asset_id, id) ON DELETE RESTRICT, 
    CONSTRAINT fk_media_asset_versions_object FOREIGN KEY(media_object_id) REFERENCES media_objects (id) ON DELETE RESTRICT, 
    CONSTRAINT uq_media_asset_versions_number UNIQUE (project_id, asset_id, version_number), 
    CONSTRAINT uq_media_asset_versions_project_asset_id UNIQUE (project_id, asset_id, id), 
    CONSTRAINT ck_media_asset_versions_ck_media_asset_versions_media_a_8a5e CHECK (version_number > 0)
);

CREATE INDEX ix_media_asset_versions_asset_created ON media_asset_versions (asset_id, created_at);

CREATE TABLE media_asset_pointers (
    id UUID NOT NULL, 
    project_id UUID NOT NULL, 
    asset_id UUID NOT NULL, 
    working_version_id UUID, 
    approved_version_id UUID, 
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    CONSTRAINT pk_media_asset_pointers PRIMARY KEY (id), 
    CONSTRAINT fk_media_asset_pointers_asset FOREIGN KEY(project_id, asset_id) REFERENCES media_assets (project_id, id) ON DELETE CASCADE, 
    CONSTRAINT fk_media_asset_pointers_working FOREIGN KEY(project_id, asset_id, working_version_id) REFERENCES media_asset_versions (project_id, asset_id, id) ON DELETE RESTRICT, 
    CONSTRAINT fk_media_asset_pointers_approved FOREIGN KEY(project_id, asset_id, approved_version_id) REFERENCES media_asset_versions (project_id, asset_id, id) ON DELETE RESTRICT, 
    CONSTRAINT uq_media_asset_pointers_asset UNIQUE (project_id, asset_id)
);

CREATE TABLE media_asset_relations (
    id UUID NOT NULL, 
    project_id UUID NOT NULL, 
    source_asset_id UUID NOT NULL, 
    target_asset_id UUID NOT NULL, 
    relation_type VARCHAR(48) NOT NULL, 
    attributes JSON NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    CONSTRAINT pk_media_asset_relations PRIMARY KEY (id), 
    CONSTRAINT fk_media_asset_relations_source FOREIGN KEY(project_id, source_asset_id) REFERENCES media_assets (project_id, id) ON DELETE CASCADE, 
    CONSTRAINT fk_media_asset_relations_target FOREIGN KEY(project_id, target_asset_id) REFERENCES media_assets (project_id, id) ON DELETE RESTRICT, 
    CONSTRAINT uq_media_asset_relation_edge UNIQUE (project_id, source_asset_id, target_asset_id, relation_type), 
    CONSTRAINT ck_media_asset_relations_ck_media_asset_relations_media_7ea9 CHECK (source_asset_id <> target_asset_id)
);

CREATE TABLE media_provenance (
    id UUID NOT NULL, 
    project_id UUID NOT NULL, 
    asset_id UUID NOT NULL, 
    asset_version_id UUID NOT NULL, 
    producer_kind VARCHAR(24) NOT NULL, 
    producer_id UUID, 
    execution_snapshot JSON NOT NULL, 
    input_asset_versions JSON NOT NULL, 
    parameters JSON NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    CONSTRAINT pk_media_provenance PRIMARY KEY (id), 
    CONSTRAINT fk_media_provenance_asset_version FOREIGN KEY(project_id, asset_id, asset_version_id) REFERENCES media_asset_versions (project_id, asset_id, id) ON DELETE RESTRICT
);

CREATE INDEX ix_media_provenance_version ON media_provenance (asset_version_id);

CREATE TABLE media_processing_jobs (
    id UUID NOT NULL, 
    project_id UUID NOT NULL, 
    asset_id UUID, 
    asset_version_id UUID, 
    job_type VARCHAR(48) NOT NULL, 
    idempotency_key VARCHAR(128) NOT NULL, 
    status VARCHAR(24) NOT NULL, 
    attempt_count INTEGER NOT NULL, 
    request_snapshot JSON NOT NULL, 
    result_snapshot JSON, 
    error_detail JSON, 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    CONSTRAINT pk_media_processing_jobs PRIMARY KEY (id), 
    CONSTRAINT fk_media_processing_jobs_asset_version FOREIGN KEY(project_id, asset_id, asset_version_id) REFERENCES media_asset_versions (project_id, asset_id, id) ON DELETE RESTRICT, 
    CONSTRAINT uq_media_processing_jobs_idempotency UNIQUE (project_id, idempotency_key), 
    CONSTRAINT ck_media_processing_jobs_ck_media_processing_jobs_media_7e9f CHECK (attempt_count >= 0), 
    CONSTRAINT ck_media_processing_jobs_ck_media_processing_jobs_media_5bde CHECK ((asset_id IS NULL AND asset_version_id IS NULL) OR (asset_id IS NOT NULL AND asset_version_id IS NOT NULL)), 
    CONSTRAINT ck_media_processing_jobs_ck_media_processing_jobs_media_e65c CHECK (status IN ('queued', 'running', 'succeeded', 'failed', 'cancelled'))
);

CREATE INDEX ix_media_processing_jobs_status_created ON media_processing_jobs (status, created_at);

CREATE TABLE media_qc_records (
    id UUID NOT NULL, 
    project_id UUID NOT NULL, 
    asset_id UUID NOT NULL, 
    asset_version_id UUID NOT NULL, 
    qc_type VARCHAR(24) NOT NULL, 
    status VARCHAR(24) NOT NULL, 
    findings JSON NOT NULL, 
    tool_snapshot JSON NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    CONSTRAINT pk_media_qc_records PRIMARY KEY (id), 
    CONSTRAINT fk_media_qc_asset_version FOREIGN KEY(project_id, asset_id, asset_version_id) REFERENCES media_asset_versions (project_id, asset_id, id) ON DELETE RESTRICT, 
    CONSTRAINT ck_media_qc_records_ck_media_qc_records_qc_type CHECK (qc_type IN ('technical', 'artistic')), 
    CONSTRAINT ck_media_qc_records_ck_media_qc_records_status CHECK (status IN ('pass', 'warning', 'fail', 'incomplete'))
);

CREATE INDEX ix_media_qc_version_type_created ON media_qc_records (asset_version_id, qc_type, created_at);

CREATE OR REPLACE FUNCTION afs_reject_media_asset_version_mutation() RETURNS trigger AS $$ BEGIN RAISE EXCEPTION 'media_asset_versions are immutable; create a new version'; END; $$ LANGUAGE plpgsql;

CREATE TRIGGER trg_media_asset_versions_immutable BEFORE UPDATE OR DELETE ON media_asset_versions FOR EACH ROW EXECUTE FUNCTION afs_reject_media_asset_version_mutation();

CREATE OR REPLACE FUNCTION afs_reject_media_object_identity_change() RETURNS trigger AS $$ BEGIN IF (NEW.storage_provider, NEW.bucket, NEW.storage_key, NEW.sha256, NEW.byte_size, NEW.mime_type) IS DISTINCT FROM (OLD.storage_provider, OLD.bucket, OLD.storage_key, OLD.sha256, OLD.byte_size, OLD.mime_type) THEN RAISE EXCEPTION 'media object identity is immutable'; END IF; RETURN NEW; END; $$ LANGUAGE plpgsql;

CREATE TRIGGER trg_media_objects_identity_immutable BEFORE UPDATE ON media_objects FOR EACH ROW EXECUTE FUNCTION afs_reject_media_object_identity_change();

UPDATE alembic_version SET version_num='0002_dam' WHERE alembic_version.version_num = '0001_core';

-- Running upgrade 0002_dam -> b626346c790e

CREATE TABLE agents (
    id UUID NOT NULL, 
    code VARCHAR(64) NOT NULL, 
    display_name VARCHAR(160) NOT NULL, 
    lifecycle_state VARCHAR(24) NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    CONSTRAINT pk_agents PRIMARY KEY (id), 
    CONSTRAINT uq_agents_code UNIQUE (code)
);

CREATE TABLE inbox_events (
    id UUID NOT NULL, 
    consumer_key VARCHAR(96) NOT NULL, 
    idempotency_key VARCHAR(160) NOT NULL, 
    event_type VARCHAR(64) NOT NULL, 
    payload JSON NOT NULL, 
    status VARCHAR(24) NOT NULL, 
    received_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    processed_at TIMESTAMP WITH TIME ZONE, 
    CONSTRAINT pk_inbox_events PRIMARY KEY (id), 
    CONSTRAINT uq_inbox_events_consumer_idempotency UNIQUE (consumer_key, idempotency_key)
);

CREATE TABLE model_providers (
    id UUID NOT NULL, 
    code VARCHAR(48) NOT NULL, 
    display_name VARCHAR(160) NOT NULL, 
    lifecycle_state VARCHAR(24) NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    CONSTRAINT pk_model_providers PRIMARY KEY (id), 
    CONSTRAINT uq_model_providers_code UNIQUE (code)
);

CREATE TABLE models (
    id UUID NOT NULL, 
    model_key VARCHAR(96) NOT NULL, 
    modality VARCHAR(32) NOT NULL, 
    capabilities JSON NOT NULL, 
    lifecycle_state VARCHAR(24) NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    CONSTRAINT pk_models PRIMARY KEY (id), 
    CONSTRAINT uq_models_model_key UNIQUE (model_key)
);

CREATE TABLE outbox_events (
    id UUID NOT NULL, 
    aggregate_type VARCHAR(48) NOT NULL, 
    aggregate_id UUID NOT NULL, 
    event_type VARCHAR(64) NOT NULL, 
    idempotency_key VARCHAR(160) NOT NULL, 
    payload JSON NOT NULL, 
    status VARCHAR(24) NOT NULL, 
    attempt_count INTEGER NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    published_at TIMESTAMP WITH TIME ZONE, 
    CONSTRAINT pk_outbox_events PRIMARY KEY (id), 
    CONSTRAINT uq_outbox_events_idempotency UNIQUE (idempotency_key)
);

CREATE INDEX ix_outbox_events_status_created ON outbox_events (status, created_at);

CREATE TABLE skills (
    id UUID NOT NULL, 
    code VARCHAR(64) NOT NULL, 
    display_name VARCHAR(160) NOT NULL, 
    lifecycle_state VARCHAR(24) NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    CONSTRAINT pk_skills PRIMARY KEY (id), 
    CONSTRAINT uq_skills_code UNIQUE (code)
);

CREATE TABLE agent_versions (
    id UUID NOT NULL, 
    agent_id UUID NOT NULL, 
    version_number INTEGER NOT NULL, 
    definition_snapshot JSON NOT NULL, 
    definition_sha256 VARCHAR(64) NOT NULL, 
    created_by UUID, 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    CONSTRAINT pk_agent_versions PRIMARY KEY (id), 
    CONSTRAINT ck_agent_versions_agent_version_number_positive CHECK (version_number > 0), 
    CONSTRAINT fk_agent_versions_agent_id_agents FOREIGN KEY(agent_id) REFERENCES agents (id) ON DELETE RESTRICT, 
    CONSTRAINT uq_agent_versions_agent_id UNIQUE (agent_id, id), 
    CONSTRAINT uq_agent_versions_number UNIQUE (agent_id, version_number)
);

