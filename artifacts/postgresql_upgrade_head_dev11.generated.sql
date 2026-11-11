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

CREATE TABLE model_provider_deployments (
    id UUID NOT NULL, 
    provider_id UUID NOT NULL, 
    model_id UUID NOT NULL, 
    deployment_key VARCHAR(128) NOT NULL, 
    region VARCHAR(64), 
    credential_ref VARCHAR(256), 
    config_snapshot JSON NOT NULL, 
    lifecycle_state VARCHAR(24) NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    CONSTRAINT pk_model_provider_deployments PRIMARY KEY (id), 
    CONSTRAINT fk_model_provider_deployments_model_id_models FOREIGN KEY(model_id) REFERENCES models (id) ON DELETE RESTRICT, 
    CONSTRAINT fk_model_provider_deployments_provider_id_model_providers FOREIGN KEY(provider_id) REFERENCES model_providers (id) ON DELETE RESTRICT, 
    CONSTRAINT uq_model_provider_deployments_model_id UNIQUE (model_id, id), 
    CONSTRAINT uq_model_provider_deployment_key UNIQUE (provider_id, deployment_key)
);

CREATE TABLE skill_versions (
    id UUID NOT NULL, 
    skill_id UUID NOT NULL, 
    version_number INTEGER NOT NULL, 
    definition_snapshot JSON NOT NULL, 
    definition_sha256 VARCHAR(64) NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    CONSTRAINT pk_skill_versions PRIMARY KEY (id), 
    CONSTRAINT ck_skill_versions_skill_version_number_positive CHECK (version_number > 0), 
    CONSTRAINT fk_skill_versions_skill_id_skills FOREIGN KEY(skill_id) REFERENCES skills (id) ON DELETE RESTRICT, 
    CONSTRAINT uq_skill_versions_skill_id UNIQUE (skill_id, id), 
    CONSTRAINT uq_skill_versions_number UNIQUE (skill_id, version_number)
);

CREATE TABLE tasks (
    id UUID NOT NULL, 
    project_id UUID NOT NULL, 
    task_type VARCHAR(64) NOT NULL, 
    title VARCHAR(240) NOT NULL, 
    status VARCHAR(24) NOT NULL, 
    priority INTEGER NOT NULL, 
    input_snapshot JSON NOT NULL, 
    created_by UUID, 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    CONSTRAINT pk_tasks PRIMARY KEY (id), 
    CONSTRAINT fk_tasks_project_id_projects FOREIGN KEY(project_id) REFERENCES projects (id) ON DELETE CASCADE, 
    CONSTRAINT uq_tasks_project_id_id UNIQUE (project_id, id)
);

CREATE INDEX ix_tasks_project_status_created ON tasks (project_id, status, created_at);

CREATE TABLE agent_messages (
    id UUID NOT NULL, 
    project_id UUID NOT NULL, 
    task_id UUID, 
    from_agent_id UUID NOT NULL, 
    to_agent_id UUID, 
    message_type VARCHAR(48) NOT NULL, 
    correlation_id UUID, 
    payload JSON NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    CONSTRAINT pk_agent_messages PRIMARY KEY (id), 
    CONSTRAINT fk_agent_messages_from_agent_id_agents FOREIGN KEY(from_agent_id) REFERENCES agents (id) ON DELETE RESTRICT, 
    CONSTRAINT fk_agent_messages_task FOREIGN KEY(project_id, task_id) REFERENCES tasks (project_id, id) ON DELETE CASCADE, 
    CONSTRAINT fk_agent_messages_project_id_projects FOREIGN KEY(project_id) REFERENCES projects (id) ON DELETE CASCADE, 
    CONSTRAINT fk_agent_messages_to_agent_id_agents FOREIGN KEY(to_agent_id) REFERENCES agents (id) ON DELETE RESTRICT
);

CREATE INDEX ix_agent_messages_project_created ON agent_messages (project_id, created_at);

CREATE TABLE agent_model_bindings (
    id UUID NOT NULL, 
    agent_version_id UUID NOT NULL, 
    model_id UUID NOT NULL, 
    deployment_id UUID NOT NULL, 
    purpose VARCHAR(48) NOT NULL, 
    priority INTEGER NOT NULL, 
    binding_config JSON NOT NULL, 
    CONSTRAINT pk_agent_model_bindings PRIMARY KEY (id), 
    CONSTRAINT ck_agent_model_bindings_agent_model_binding_priority_no_1a52 CHECK (priority >= 0), 
    CONSTRAINT fk_agent_model_bindings_agent_version_id_agent_versions FOREIGN KEY(agent_version_id) REFERENCES agent_versions (id) ON DELETE CASCADE, 
    CONSTRAINT fk_agent_model_binding_deployment FOREIGN KEY(model_id, deployment_id) REFERENCES model_provider_deployments (model_id, id) ON DELETE RESTRICT, 
    CONSTRAINT uq_agent_model_binding_priority UNIQUE (agent_version_id, purpose, priority)
);

CREATE TABLE agent_runs (
    id UUID NOT NULL, 
    project_id UUID NOT NULL, 
    task_id UUID NOT NULL, 
    agent_id UUID NOT NULL, 
    agent_version_id UUID NOT NULL, 
    status VARCHAR(24) NOT NULL, 
    input_snapshot JSON NOT NULL, 
    output_snapshot JSON, 
    error_detail JSON, 
    started_at TIMESTAMP WITH TIME ZONE, 
    finished_at TIMESTAMP WITH TIME ZONE, 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    CONSTRAINT pk_agent_runs PRIMARY KEY (id), 
    CONSTRAINT fk_agent_runs_agent_version FOREIGN KEY(agent_id, agent_version_id) REFERENCES agent_versions (agent_id, id) ON DELETE RESTRICT, 
    CONSTRAINT fk_agent_runs_task FOREIGN KEY(project_id, task_id) REFERENCES tasks (project_id, id) ON DELETE RESTRICT, 
    CONSTRAINT uq_agent_runs_project_id_id UNIQUE (project_id, id)
);

CREATE INDEX ix_agent_runs_project_status_created ON agent_runs (project_id, status, created_at);

CREATE TABLE agent_skill_bindings (
    id UUID NOT NULL, 
    agent_version_id UUID NOT NULL, 
    skill_version_id UUID NOT NULL, 
    binding_config JSON NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    CONSTRAINT pk_agent_skill_bindings PRIMARY KEY (id), 
    CONSTRAINT fk_agent_skill_bindings_agent_version_id_agent_versions FOREIGN KEY(agent_version_id) REFERENCES agent_versions (id) ON DELETE CASCADE, 
    CONSTRAINT fk_agent_skill_bindings_skill_version_id_skill_versions FOREIGN KEY(skill_version_id) REFERENCES skill_versions (id) ON DELETE RESTRICT, 
    CONSTRAINT uq_agent_skill_binding UNIQUE (agent_version_id, skill_version_id)
);

CREATE TABLE agent_version_pointers (
    id UUID NOT NULL, 
    agent_id UUID NOT NULL, 
    active_version_id UUID, 
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    CONSTRAINT pk_agent_version_pointers PRIMARY KEY (id), 
    CONSTRAINT fk_agent_version_pointers_active FOREIGN KEY(agent_id, active_version_id) REFERENCES agent_versions (agent_id, id) ON DELETE RESTRICT, 
    CONSTRAINT fk_agent_version_pointers_agent_id_agents FOREIGN KEY(agent_id) REFERENCES agents (id) ON DELETE CASCADE, 
    CONSTRAINT uq_agent_version_pointers_agent UNIQUE (agent_id)
);

CREATE TABLE orchestration_plans (
    id UUID NOT NULL, 
    project_id UUID NOT NULL, 
    task_id UUID NOT NULL, 
    status VARCHAR(24) NOT NULL, 
    plan_snapshot JSON NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    CONSTRAINT pk_orchestration_plans PRIMARY KEY (id), 
    CONSTRAINT fk_orchestration_plans_task FOREIGN KEY(project_id, task_id) REFERENCES tasks (project_id, id) ON DELETE CASCADE, 
    CONSTRAINT uq_orchestration_plans_project_id_id UNIQUE (project_id, id)
);

CREATE TABLE skill_version_pointers (
    id UUID NOT NULL, 
    skill_id UUID NOT NULL, 
    active_version_id UUID, 
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    CONSTRAINT pk_skill_version_pointers PRIMARY KEY (id), 
    CONSTRAINT fk_skill_version_pointers_active FOREIGN KEY(skill_id, active_version_id) REFERENCES skill_versions (skill_id, id) ON DELETE RESTRICT, 
    CONSTRAINT fk_skill_version_pointers_skill_id_skills FOREIGN KEY(skill_id) REFERENCES skills (id) ON DELETE CASCADE, 
    CONSTRAINT uq_skill_version_pointers_skill UNIQUE (skill_id)
);

CREATE TABLE task_dependencies (
    id UUID NOT NULL, 
    project_id UUID NOT NULL, 
    task_id UUID NOT NULL, 
    depends_on_task_id UUID NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    CONSTRAINT pk_task_dependencies PRIMARY KEY (id), 
    CONSTRAINT ck_task_dependencies_task_dependency_not_self CHECK (task_id <> depends_on_task_id), 
    CONSTRAINT fk_task_dependencies_parent FOREIGN KEY(project_id, depends_on_task_id) REFERENCES tasks (project_id, id) ON DELETE RESTRICT, 
    CONSTRAINT fk_task_dependencies_task FOREIGN KEY(project_id, task_id) REFERENCES tasks (project_id, id) ON DELETE CASCADE, 
    CONSTRAINT uq_task_dependency_edge UNIQUE (project_id, task_id, depends_on_task_id)
);

CREATE TABLE orchestration_plan_steps (
    id UUID NOT NULL, 
    plan_id UUID NOT NULL, 
    step_order INTEGER NOT NULL, 
    agent_version_id UUID, 
    skill_version_id UUID, 
    step_kind VARCHAR(32) NOT NULL, 
    input_snapshot JSON NOT NULL, 
    status VARCHAR(24) NOT NULL, 
    CONSTRAINT pk_orchestration_plan_steps PRIMARY KEY (id), 
    CONSTRAINT ck_orchestration_plan_steps_orchestration_plan_step_exa_38c8 CHECK ((agent_version_id IS NOT NULL AND skill_version_id IS NULL) OR (agent_version_id IS NULL AND skill_version_id IS NOT NULL)), 
    CONSTRAINT ck_orchestration_plan_steps_orchestration_plan_step_ord_5744 CHECK (step_order > 0), 
    CONSTRAINT fk_orchestration_plan_steps_agent_version_id_agent_versions FOREIGN KEY(agent_version_id) REFERENCES agent_versions (id) ON DELETE RESTRICT, 
    CONSTRAINT fk_orchestration_plan_steps_plan_id_orchestration_plans FOREIGN KEY(plan_id) REFERENCES orchestration_plans (id) ON DELETE CASCADE, 
    CONSTRAINT fk_orchestration_plan_steps_skill_version_id_skill_versions FOREIGN KEY(skill_version_id) REFERENCES skill_versions (id) ON DELETE RESTRICT, 
    CONSTRAINT uq_orchestration_plan_steps_order UNIQUE (plan_id, step_order)
);

CREATE TABLE run_events (
    id UUID NOT NULL, 
    project_id UUID NOT NULL, 
    agent_run_id UUID NOT NULL, 
    event_type VARCHAR(64) NOT NULL, 
    payload JSON NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    CONSTRAINT pk_run_events PRIMARY KEY (id), 
    CONSTRAINT fk_run_events_agent_run FOREIGN KEY(project_id, agent_run_id) REFERENCES agent_runs (project_id, id) ON DELETE CASCADE
);

CREATE INDEX ix_run_events_agent_run_created ON run_events (agent_run_id, created_at);

CREATE TABLE skill_runs (
    id UUID NOT NULL, 
    project_id UUID NOT NULL, 
    agent_run_id UUID NOT NULL, 
    skill_id UUID NOT NULL, 
    skill_version_id UUID NOT NULL, 
    status VARCHAR(24) NOT NULL, 
    input_snapshot JSON NOT NULL, 
    output_snapshot JSON, 
    started_at TIMESTAMP WITH TIME ZONE, 
    finished_at TIMESTAMP WITH TIME ZONE, 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    CONSTRAINT pk_skill_runs PRIMARY KEY (id), 
    CONSTRAINT fk_skill_runs_agent_run FOREIGN KEY(project_id, agent_run_id) REFERENCES agent_runs (project_id, id) ON DELETE CASCADE, 
    CONSTRAINT fk_skill_runs_skill_version FOREIGN KEY(skill_id, skill_version_id) REFERENCES skill_versions (skill_id, id) ON DELETE RESTRICT, 
    CONSTRAINT uq_skill_runs_project_id_id UNIQUE (project_id, id)
);

CREATE INDEX ix_skill_runs_agent_run ON skill_runs (agent_run_id);

CREATE TABLE model_runs (
    id UUID NOT NULL, 
    project_id UUID NOT NULL, 
    agent_run_id UUID NOT NULL, 
    skill_run_id UUID, 
    model_id UUID NOT NULL, 
    deployment_id UUID NOT NULL, 
    status VARCHAR(24) NOT NULL, 
    request_snapshot JSON NOT NULL, 
    response_snapshot JSON, 
    provider_request_id VARCHAR(160), 
    usage_snapshot JSON, 
    cost_amount VARCHAR(48), 
    started_at TIMESTAMP WITH TIME ZONE, 
    finished_at TIMESTAMP WITH TIME ZONE, 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    CONSTRAINT pk_model_runs PRIMARY KEY (id), 
    CONSTRAINT fk_model_runs_deployment FOREIGN KEY(model_id, deployment_id) REFERENCES model_provider_deployments (model_id, id) ON DELETE RESTRICT, 
    CONSTRAINT fk_model_runs_agent_run FOREIGN KEY(project_id, agent_run_id) REFERENCES agent_runs (project_id, id) ON DELETE CASCADE, 
    CONSTRAINT fk_model_runs_skill_run FOREIGN KEY(project_id, skill_run_id) REFERENCES skill_runs (project_id, id) ON DELETE RESTRICT, 
    CONSTRAINT uq_model_runs_project_id_id UNIQUE (project_id, id)
);

CREATE INDEX ix_model_runs_agent_run ON model_runs (agent_run_id);

CREATE TABLE run_artifacts (
    id UUID NOT NULL, 
    project_id UUID NOT NULL, 
    agent_run_id UUID, 
    skill_run_id UUID, 
    model_run_id UUID, 
    media_asset_id UUID, 
    media_asset_version_id UUID, 
    artifact_role VARCHAR(48) NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    CONSTRAINT pk_run_artifacts PRIMARY KEY (id), 
    CONSTRAINT ck_run_artifacts_run_artifact_exactly_one_owner CHECK ((CASE WHEN agent_run_id IS NULL THEN 0 ELSE 1 END + CASE WHEN skill_run_id IS NULL THEN 0 ELSE 1 END + CASE WHEN model_run_id IS NULL THEN 0 ELSE 1 END) = 1), 
    CONSTRAINT ck_run_artifacts_run_artifact_media_version_pair CHECK ((media_asset_id IS NULL AND media_asset_version_id IS NULL) OR (media_asset_id IS NOT NULL AND media_asset_version_id IS NOT NULL)), 
    CONSTRAINT fk_run_artifacts_agent_run FOREIGN KEY(project_id, agent_run_id) REFERENCES agent_runs (project_id, id) ON DELETE CASCADE, 
    CONSTRAINT fk_run_artifacts_media_version FOREIGN KEY(project_id, media_asset_id, media_asset_version_id) REFERENCES media_asset_versions (project_id, asset_id, id) ON DELETE RESTRICT, 
    CONSTRAINT fk_run_artifacts_model_run FOREIGN KEY(project_id, model_run_id) REFERENCES model_runs (project_id, id) ON DELETE CASCADE, 
    CONSTRAINT fk_run_artifacts_skill_run FOREIGN KEY(project_id, skill_run_id) REFERENCES skill_runs (project_id, id) ON DELETE CASCADE
);

CREATE OR REPLACE FUNCTION afs_reject_registry_version_mutation() RETURNS trigger AS $$ BEGIN RAISE EXCEPTION 'agent/skill version snapshots are immutable'; END; $$ LANGUAGE plpgsql;

CREATE TRIGGER trg_agent_versions_immutable BEFORE UPDATE OR DELETE ON agent_versions FOR EACH ROW EXECUTE FUNCTION afs_reject_registry_version_mutation();

CREATE TRIGGER trg_skill_versions_immutable BEFORE UPDATE OR DELETE ON skill_versions FOR EACH ROW EXECUTE FUNCTION afs_reject_registry_version_mutation();

CREATE OR REPLACE FUNCTION afs_guard_run_input_snapshot() RETURNS trigger AS $$ BEGIN
          IF TG_OP = 'DELETE' THEN RAISE EXCEPTION 'execution records are append-only'; END IF;
          IF TG_TABLE_NAME = 'agent_runs' AND (NEW.project_id, NEW.task_id, NEW.agent_id, NEW.agent_version_id, NEW.input_snapshot) IS DISTINCT FROM (OLD.project_id, OLD.task_id, OLD.agent_id, OLD.agent_version_id, OLD.input_snapshot) THEN RAISE EXCEPTION 'agent run input snapshot is immutable'; END IF;
          IF TG_TABLE_NAME = 'skill_runs' AND (NEW.project_id, NEW.agent_run_id, NEW.skill_id, NEW.skill_version_id, NEW.input_snapshot) IS DISTINCT FROM (OLD.project_id, OLD.agent_run_id, OLD.skill_id, OLD.skill_version_id, OLD.input_snapshot) THEN RAISE EXCEPTION 'skill run input snapshot is immutable'; END IF;
          IF TG_TABLE_NAME = 'model_runs' AND (NEW.project_id, NEW.agent_run_id, NEW.skill_run_id, NEW.model_id, NEW.deployment_id, NEW.request_snapshot) IS DISTINCT FROM (OLD.project_id, OLD.agent_run_id, OLD.skill_run_id, OLD.model_id, OLD.deployment_id, OLD.request_snapshot) THEN RAISE EXCEPTION 'model run request snapshot is immutable'; END IF;
          RETURN NEW; END; $$ LANGUAGE plpgsql;

CREATE TRIGGER trg_agent_runs_snapshot_guard BEFORE UPDATE OR DELETE ON agent_runs FOR EACH ROW EXECUTE FUNCTION afs_guard_run_input_snapshot();

CREATE TRIGGER trg_skill_runs_snapshot_guard BEFORE UPDATE OR DELETE ON skill_runs FOR EACH ROW EXECUTE FUNCTION afs_guard_run_input_snapshot();

CREATE TRIGGER trg_model_runs_snapshot_guard BEFORE UPDATE OR DELETE ON model_runs FOR EACH ROW EXECUTE FUNCTION afs_guard_run_input_snapshot();

UPDATE alembic_version SET version_num='b626346c790e' WHERE alembic_version.version_num = '0002_dam';

-- Running upgrade b626346c790e -> 8c58a10612ac

CREATE TABLE integration_sources (
    id UUID NOT NULL, 
    project_id UUID NOT NULL, 
    code VARCHAR(64) NOT NULL, 
    source_kind VARCHAR(32) NOT NULL, 
    display_name VARCHAR(160) NOT NULL, 
    source_version VARCHAR(64), 
    source_sha256 VARCHAR(64), 
    config_snapshot JSON NOT NULL, 
    lifecycle_state VARCHAR(24) NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    CONSTRAINT pk_integration_sources PRIMARY KEY (id), 
    CONSTRAINT fk_integration_sources_project FOREIGN KEY(project_id) REFERENCES projects (id) ON DELETE CASCADE, 
    CONSTRAINT uq_integration_sources_project_code UNIQUE (project_id, code), 
    CONSTRAINT uq_integration_sources_project_id UNIQUE (project_id, id)
);

CREATE TABLE integration_object_mappings (
    id UUID NOT NULL, 
    project_id UUID NOT NULL, 
    integration_source_id UUID NOT NULL, 
    source_object_type VARCHAR(48) NOT NULL, 
    source_object_key VARCHAR(256) NOT NULL, 
    canonical_entity_id UUID, 
    mapping_state VARCHAR(24) NOT NULL, 
    mapping_snapshot JSON NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    CONSTRAINT pk_integration_object_mappings PRIMARY KEY (id), 
    CONSTRAINT ck_integration_object_mappings_integration_mapping_enti_cb05 CHECK ((mapping_state = 'mapped' AND canonical_entity_id IS NOT NULL) OR (mapping_state <> 'mapped' AND canonical_entity_id IS NULL)), 
    CONSTRAINT ck_integration_object_mappings_integration_mapping_state_valid CHECK (mapping_state IN ('unmapped', 'mapped', 'conflict', 'retired')), 
    CONSTRAINT fk_integration_object_mappings_entity FOREIGN KEY(project_id, canonical_entity_id) REFERENCES entities (project_id, id) ON DELETE RESTRICT, 
    CONSTRAINT fk_integration_object_mappings_source FOREIGN KEY(project_id, integration_source_id) REFERENCES integration_sources (project_id, id) ON DELETE CASCADE, 
    CONSTRAINT uq_integration_object_mapping_source_key UNIQUE (integration_source_id, source_object_type, source_object_key)
);

CREATE TABLE integration_runs (
    id UUID NOT NULL, 
    project_id UUID NOT NULL, 
    integration_source_id UUID NOT NULL, 
    run_type VARCHAR(24) NOT NULL, 
    status VARCHAR(24) NOT NULL, 
    idempotency_key VARCHAR(160) NOT NULL, 
    package_version VARCHAR(64), 
    package_sha256 VARCHAR(64), 
    command_snapshot JSON NOT NULL, 
    input_snapshot JSON NOT NULL, 
    output_snapshot JSON, 
    validation_snapshot JSON, 
    exit_code INTEGER, 
    error_detail JSON, 
    started_at TIMESTAMP WITH TIME ZONE, 
    finished_at TIMESTAMP WITH TIME ZONE, 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    CONSTRAINT pk_integration_runs PRIMARY KEY (id), 
    CONSTRAINT fk_integration_runs_source FOREIGN KEY(project_id, integration_source_id) REFERENCES integration_sources (project_id, id) ON DELETE RESTRICT, 
    CONSTRAINT uq_integration_runs_idempotency UNIQUE (integration_source_id, idempotency_key), 
    CONSTRAINT uq_integration_runs_project_id UNIQUE (project_id, id)
);

CREATE INDEX ix_integration_runs_project_status_created ON integration_runs (project_id, status, created_at);

CREATE TABLE fm_coverage_decisions (
    id UUID NOT NULL, 
    project_id UUID NOT NULL, 
    integration_run_id UUID NOT NULL, 
    event_entity_id UUID, 
    event_source_key VARCHAR(160) NOT NULL, 
    coverage_status VARCHAR(24) NOT NULL, 
    required_dimensions JSON NOT NULL, 
    covered_dimensions JSON NOT NULL, 
    selected_shot_source_keys JSON NOT NULL, 
    selected_shot_entity_ids JSON NOT NULL, 
    source_range_snapshot JSON NOT NULL, 
    confidence FLOAT, 
    human_review_required BOOLEAN NOT NULL, 
    review_state VARCHAR(24) NOT NULL, 
    decision_snapshot JSON NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    CONSTRAINT pk_fm_coverage_decisions PRIMARY KEY (id), 
    CONSTRAINT ck_fm_coverage_decisions_fm_coverage_status_valid CHECK (coverage_status IN ('covered', 'partially_covered', 'not_selected')), 
    CONSTRAINT ck_fm_coverage_decisions_fm_coverage_review_state_valid CHECK (review_state IN ('proposed', 'under_review', 'approval_pending')), 
    CONSTRAINT ck_fm_coverage_decisions_fm_coverage_confidence_range CHECK (confidence IS NULL OR (confidence >= 0 AND confidence <= 1)), 
    CONSTRAINT fk_fm_coverage_decisions_event FOREIGN KEY(project_id, event_entity_id) REFERENCES entities (project_id, id) ON DELETE RESTRICT, 
    CONSTRAINT fk_fm_coverage_decisions_run FOREIGN KEY(project_id, integration_run_id) REFERENCES integration_runs (project_id, id) ON DELETE CASCADE
);

CREATE TABLE fm_performance_tracks (
    id UUID NOT NULL, 
    project_id UUID NOT NULL, 
    integration_run_id UUID NOT NULL, 
    track_key VARCHAR(160) NOT NULL, 
    track_kind VARCHAR(24) NOT NULL, 
    character_entity_id UUID, 
    concurrency_group VARCHAR(128), 
    parallel_with JSON NOT NULL, 
    timing_provenance JSON NOT NULL, 
    track_snapshot JSON NOT NULL, 
    CONSTRAINT pk_fm_performance_tracks PRIMARY KEY (id), 
    CONSTRAINT ck_fm_performance_tracks_fm_performance_track_kind_valid CHECK (track_kind IN ('character', 'group', 'environment', 'other')), 
    CONSTRAINT fk_fm_performance_tracks_character FOREIGN KEY(project_id, character_entity_id) REFERENCES entities (project_id, id) ON DELETE RESTRICT, 
    CONSTRAINT fk_fm_performance_tracks_run FOREIGN KEY(project_id, integration_run_id) REFERENCES integration_runs (project_id, id) ON DELETE CASCADE, 
    CONSTRAINT uq_fm_performance_track_key UNIQUE (integration_run_id, track_key)
);

CREATE TABLE fm_source_ranges (
    id UUID NOT NULL, 
    project_id UUID NOT NULL, 
    integration_run_id UUID NOT NULL, 
    canonical_entity_id UUID, 
    source_kind VARCHAR(32) NOT NULL, 
    source_object_key VARCHAR(256), 
    line_start INTEGER, 
    line_end INTEGER, 
    exact_text TEXT, 
    time_start_ms INTEGER, 
    time_end_ms INTEGER, 
    timing_source VARCHAR(16) NOT NULL, 
    range_snapshot JSON NOT NULL, 
    CONSTRAINT pk_fm_source_ranges PRIMARY KEY (id), 
    CONSTRAINT ck_fm_source_ranges_fm_source_range_timing_source_valid CHECK (timing_source IN ('authored', 'estimated', 'measured', 'unknown')), 
    CONSTRAINT ck_fm_source_ranges_fm_source_range_line_order CHECK ((line_start IS NULL AND line_end IS NULL) OR (line_start > 0 AND line_end >= line_start)), 
    CONSTRAINT ck_fm_source_ranges_fm_source_range_time_order CHECK ((time_start_ms IS NULL AND time_end_ms IS NULL) OR (time_start_ms >= 0 AND time_end_ms >= time_start_ms)), 
    CONSTRAINT fk_fm_source_ranges_entity FOREIGN KEY(project_id, canonical_entity_id) REFERENCES entities (project_id, id) ON DELETE RESTRICT, 
    CONSTRAINT fk_fm_source_ranges_run FOREIGN KEY(project_id, integration_run_id) REFERENCES integration_runs (project_id, id) ON DELETE CASCADE
);

CREATE TABLE integration_object_snapshots (
    id UUID NOT NULL, 
    project_id UUID NOT NULL, 
    integration_run_id UUID NOT NULL, 
    source_object_type VARCHAR(48) NOT NULL, 
    source_object_key VARCHAR(256) NOT NULL, 
    raw_payload JSON NOT NULL, 
    raw_sha256 VARCHAR(64) NOT NULL, 
    source_range_snapshot JSON NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    CONSTRAINT pk_integration_object_snapshots PRIMARY KEY (id), 
    CONSTRAINT ck_integration_object_snapshots_integration_snapshot_sh_25d9 CHECK (length(raw_sha256) = 64), 
    CONSTRAINT fk_integration_object_snapshots_run FOREIGN KEY(project_id, integration_run_id) REFERENCES integration_runs (project_id, id) ON DELETE CASCADE, 
    CONSTRAINT uq_integration_object_snapshot_source_key UNIQUE (integration_run_id, source_object_type, source_object_key)
);

CREATE INDEX ix_integration_object_snapshots_source_key ON integration_object_snapshots (source_object_type, source_object_key);

CREATE OR REPLACE FUNCTION afs_guard_integration_snapshot() RETURNS trigger AS $$ BEGIN
          IF TG_OP = 'DELETE' THEN RAISE EXCEPTION 'integration source snapshots are append-only'; END IF;
          IF TG_TABLE_NAME IN ('integration_object_snapshots', 'fm_source_ranges', 'fm_performance_tracks') THEN RAISE EXCEPTION 'integration source snapshots are immutable'; END IF;
          IF TG_TABLE_NAME = 'integration_runs' AND (NEW.project_id, NEW.integration_source_id, NEW.run_type, NEW.idempotency_key, NEW.package_version, NEW.package_sha256, NEW.command_snapshot, NEW.input_snapshot) IS DISTINCT FROM (OLD.project_id, OLD.integration_source_id, OLD.run_type, OLD.idempotency_key, OLD.package_version, OLD.package_sha256, OLD.command_snapshot, OLD.input_snapshot) THEN RAISE EXCEPTION 'integration run input provenance is immutable'; END IF;
          IF TG_TABLE_NAME = 'fm_coverage_decisions' AND (NEW.project_id, NEW.integration_run_id, NEW.event_entity_id, NEW.event_source_key, NEW.coverage_status, NEW.required_dimensions, NEW.covered_dimensions, NEW.selected_shot_source_keys, NEW.selected_shot_entity_ids, NEW.source_range_snapshot, NEW.confidence, NEW.human_review_required, NEW.decision_snapshot) IS DISTINCT FROM (OLD.project_id, OLD.integration_run_id, OLD.event_entity_id, OLD.event_source_key, OLD.coverage_status, OLD.required_dimensions, OLD.covered_dimensions, OLD.selected_shot_source_keys, OLD.selected_shot_entity_ids, OLD.source_range_snapshot, OLD.confidence, OLD.human_review_required, OLD.decision_snapshot) THEN RAISE EXCEPTION 'coverage decision proposal is immutable; create a reviewed record'; END IF;
          RETURN NEW; END; $$ LANGUAGE plpgsql;

CREATE TRIGGER trg_integration_runs_provenance_guard BEFORE UPDATE OR DELETE ON integration_runs FOR EACH ROW EXECUTE FUNCTION afs_guard_integration_snapshot();

CREATE TRIGGER trg_integration_object_snapshots_provenance_guard BEFORE UPDATE OR DELETE ON integration_object_snapshots FOR EACH ROW EXECUTE FUNCTION afs_guard_integration_snapshot();

CREATE TRIGGER trg_fm_source_ranges_provenance_guard BEFORE UPDATE OR DELETE ON fm_source_ranges FOR EACH ROW EXECUTE FUNCTION afs_guard_integration_snapshot();

CREATE TRIGGER trg_fm_performance_tracks_provenance_guard BEFORE UPDATE OR DELETE ON fm_performance_tracks FOR EACH ROW EXECUTE FUNCTION afs_guard_integration_snapshot();

CREATE TRIGGER trg_fm_coverage_decisions_provenance_guard BEFORE UPDATE OR DELETE ON fm_coverage_decisions FOR EACH ROW EXECUTE FUNCTION afs_guard_integration_snapshot();

UPDATE alembic_version SET version_num='8c58a10612ac' WHERE alembic_version.version_num = 'b626346c790e';

-- Running upgrade 8c58a10612ac -> 13a9c2e4f601

ALTER TABLE tasks ADD COLUMN output_snapshot JSON;

ALTER TABLE tasks ADD COLUMN idempotency_key VARCHAR(160);

ALTER TABLE tasks ADD COLUMN attempt_count INTEGER DEFAULT '0' NOT NULL;

ALTER TABLE tasks ADD COLUMN max_attempts INTEGER DEFAULT '3' NOT NULL;

ALTER TABLE tasks ADD COLUMN lease_owner VARCHAR(128);

ALTER TABLE tasks ADD COLUMN lease_token VARCHAR(36);

ALTER TABLE tasks ADD COLUMN lease_expires_at TIMESTAMP WITH TIME ZONE;

ALTER TABLE tasks ADD COLUMN retry_after TIMESTAMP WITH TIME ZONE;

ALTER TABLE tasks ADD COLUMN cancel_requested BOOLEAN DEFAULT false NOT NULL;

ALTER TABLE tasks ADD COLUMN started_at TIMESTAMP WITH TIME ZONE;

ALTER TABLE tasks ADD COLUMN finished_at TIMESTAMP WITH TIME ZONE;

ALTER TABLE tasks ADD COLUMN error_detail JSON;

ALTER TABLE tasks ADD CONSTRAINT uq_tasks_project_idempotency UNIQUE (project_id, idempotency_key);

ALTER TABLE tasks ADD CONSTRAINT ck_tasks_task_attempt_bounds CHECK (attempt_count >= 0 AND max_attempts > 0 AND attempt_count <= max_attempts);

ALTER TABLE tasks ADD CONSTRAINT ck_tasks_task_status_valid CHECK (status IN ('queued', 'running', 'retry_wait', 'succeeded', 'failed', 'cancelled'));

UPDATE alembic_version SET version_num='13a9c2e4f601' WHERE alembic_version.version_num = '8c58a10612ac';

-- Running upgrade 13a9c2e4f601 -> 4d9c2a7e1f30

ALTER TABLE outbox_events ADD COLUMN max_attempts INTEGER DEFAULT '8' NOT NULL;

ALTER TABLE outbox_events ADD COLUMN next_attempt_at TIMESTAMP WITH TIME ZONE;

ALTER TABLE outbox_events ADD COLUMN claimed_by VARCHAR(128);

ALTER TABLE outbox_events ADD COLUMN claim_token VARCHAR(36);

ALTER TABLE outbox_events ADD COLUMN claim_expires_at TIMESTAMP WITH TIME ZONE;

ALTER TABLE outbox_events ADD COLUMN last_error JSON;

ALTER TABLE outbox_events ADD CONSTRAINT ck_outbox_events_outbox_attempt_bounds CHECK (attempt_count >= 0 AND max_attempts > 0);

ALTER TABLE outbox_events ADD CONSTRAINT ck_outbox_events_outbox_status_valid CHECK (status IN ('pending', 'publishing', 'published', 'dead'));

CREATE TABLE worker_instances (
    id UUID NOT NULL, 
    worker_id VARCHAR(128) NOT NULL, 
    process_id INTEGER, 
    host_name VARCHAR(160), 
    status VARCHAR(24) NOT NULL, 
    capabilities JSON NOT NULL, 
    metadata_snapshot JSON NOT NULL, 
    started_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    last_heartbeat_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    stopped_at TIMESTAMP WITH TIME ZONE, 
    CONSTRAINT pk_worker_instances PRIMARY KEY (id), 
    CONSTRAINT ck_worker_instances_worker_instance_status_valid CHECK (status IN ('starting', 'online', 'stopping', 'offline', 'stale')), 
    CONSTRAINT uq_worker_instances_worker_id UNIQUE (worker_id)
);

CREATE INDEX ix_worker_instances_status_heartbeat ON worker_instances (status, last_heartbeat_at);

CREATE TABLE task_dead_letters (
    id UUID NOT NULL, 
    project_id UUID NOT NULL, 
    task_id UUID NOT NULL, 
    task_type VARCHAR(64) NOT NULL, 
    attempt_count INTEGER NOT NULL, 
    input_snapshot JSON NOT NULL, 
    error_detail JSON NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    resolved_at TIMESTAMP WITH TIME ZONE, 
    resolution_note TEXT, 
    CONSTRAINT pk_task_dead_letters PRIMARY KEY (id), 
    CONSTRAINT fk_task_dead_letters_task FOREIGN KEY(project_id, task_id) REFERENCES tasks (project_id, id) ON DELETE RESTRICT, 
    CONSTRAINT uq_task_dead_letters_task UNIQUE (task_id)
);

CREATE INDEX ix_task_dead_letters_created ON task_dead_letters (created_at);

UPDATE alembic_version SET version_num='4d9c2a7e1f30' WHERE alembic_version.version_num = '13a9c2e4f601';

-- Running upgrade 4d9c2a7e1f30 -> 7f31b6c2a904

ALTER TABLE worker_instances ADD COLUMN instance_token VARCHAR(36) DEFAULT 'legacy' NOT NULL;

ALTER TABLE worker_instances ALTER COLUMN instance_token DROP DEFAULT;

UPDATE alembic_version SET version_num='7f31b6c2a904' WHERE alembic_version.version_num = '4d9c2a7e1f30';

-- Running upgrade 7f31b6c2a904 -> 2c84a1d9e650

ALTER TABLE orchestration_plan_steps ADD COLUMN step_key VARCHAR(96);

ALTER TABLE orchestration_plan_steps ADD COLUMN task_id UUID;

ALTER TABLE orchestration_plan_steps ADD COLUMN depends_on_step_keys JSON DEFAULT '[]' NOT NULL;

ALTER TABLE orchestration_plan_steps ADD COLUMN output_snapshot JSON;

ALTER TABLE orchestration_plan_steps ADD COLUMN error_detail JSON;

ALTER TABLE orchestration_plan_steps ADD COLUMN started_at TIMESTAMP WITH TIME ZONE;

ALTER TABLE orchestration_plan_steps ADD COLUMN finished_at TIMESTAMP WITH TIME ZONE;

ALTER TABLE orchestration_plan_steps ADD CONSTRAINT uq_orchestration_plan_step_task UNIQUE (task_id);

ALTER TABLE orchestration_plan_steps ADD CONSTRAINT fk_orchestration_plan_step_task FOREIGN KEY(task_id) REFERENCES tasks (id) ON DELETE RESTRICT;

CREATE UNIQUE INDEX ix_orchestration_plan_steps_plan_key ON orchestration_plan_steps (plan_id, step_key);

UPDATE alembic_version SET version_num='2c84a1d9e650' WHERE alembic_version.version_num = '7f31b6c2a904';

-- Running upgrade 2c84a1d9e650 -> 5e92c1a7d4b8

ALTER TABLE orchestration_plans ADD COLUMN approval_status VARCHAR(24) DEFAULT 'pending' NOT NULL;

ALTER TABLE orchestration_plans ADD COLUMN approved_by UUID;

ALTER TABLE orchestration_plans ADD COLUMN approval_decided_at TIMESTAMP WITH TIME ZONE;

ALTER TABLE orchestration_plans ADD COLUMN approval_note TEXT;

ALTER TABLE orchestration_plans ADD COLUMN plan_sha256 VARCHAR(64) DEFAULT '' NOT NULL;

ALTER TABLE orchestration_plans ADD CONSTRAINT ck_orchestration_plans_ck_orchestration_plan_approval_status CHECK (approval_status IN ('pending', 'approved', 'rejected'));

ALTER TABLE orchestration_plans ALTER COLUMN approval_status DROP DEFAULT;

ALTER TABLE orchestration_plans ALTER COLUMN plan_sha256 DROP DEFAULT;

UPDATE alembic_version SET version_num='5e92c1a7d4b8' WHERE alembic_version.version_num = '2c84a1d9e650';

-- Running upgrade 5e92c1a7d4b8 -> 9c6e2a41b7d0

ALTER TABLE agent_messages ADD COLUMN idempotency_key VARCHAR(160);

ALTER TABLE agent_messages ADD CONSTRAINT uq_agent_messages_idempotency UNIQUE (project_id, idempotency_key);

CREATE TABLE agent_evaluations (
    id UUID NOT NULL, 
    project_id UUID NOT NULL, 
    task_id UUID NOT NULL, 
    agent_run_id UUID NOT NULL, 
    reviewer_agent_version_id UUID NOT NULL, 
    decision VARCHAR(24) NOT NULL, 
    score FLOAT NOT NULL, 
    rework_round INTEGER DEFAULT '0' NOT NULL, 
    rubric_snapshot JSON NOT NULL, 
    findings JSON NOT NULL, 
    required_changes JSON NOT NULL, 
    idempotency_key VARCHAR(160) NOT NULL, 
    rework_task_id UUID, 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    CONSTRAINT pk_agent_evaluations PRIMARY KEY (id), 
    CONSTRAINT ck_agent_evaluations_agent_evaluation_score_range CHECK (score >= 0 AND score <= 1), 
    CONSTRAINT ck_agent_evaluations_agent_evaluation_decision_valid CHECK (decision IN ('accepted', 'rework', 'escalate')), 
    CONSTRAINT ck_agent_evaluations_agent_evaluation_rework_round_nonnegative CHECK (rework_round >= 0), 
    CONSTRAINT fk_agent_evaluations_agent_run FOREIGN KEY(project_id, agent_run_id) REFERENCES agent_runs (project_id, id) ON DELETE RESTRICT, 
    CONSTRAINT fk_agent_evaluations_task FOREIGN KEY(project_id, task_id) REFERENCES tasks (project_id, id) ON DELETE RESTRICT, 
    CONSTRAINT fk_agent_evaluations_reviewer_agent_version_id_agent_versions FOREIGN KEY(reviewer_agent_version_id) REFERENCES agent_versions (id) ON DELETE RESTRICT, 
    CONSTRAINT fk_agent_evaluations_rework_task_project FOREIGN KEY(project_id, rework_task_id) REFERENCES tasks (project_id, id) ON DELETE RESTRICT, 
    CONSTRAINT uq_agent_evaluations_idempotency UNIQUE (project_id, idempotency_key), 
    CONSTRAINT uq_agent_evaluations_rework_task UNIQUE (rework_task_id)
);

CREATE INDEX ix_agent_evaluations_run_created ON agent_evaluations (agent_run_id, created_at);

ALTER TABLE agent_evaluations ALTER COLUMN rework_round DROP DEFAULT;

UPDATE alembic_version SET version_num='9c6e2a41b7d0' WHERE alembic_version.version_num = '5e92c1a7d4b8';

-- Running upgrade 9c6e2a41b7d0 -> a41d7c2e9b60

CREATE TABLE director_decision_cases (
    id UUID NOT NULL, 
    project_id UUID NOT NULL, 
    case_key VARCHAR(64) NOT NULL, 
    source_brief_sha256 VARCHAR(64) NOT NULL, 
    source_state_digest VARCHAR(64) NOT NULL, 
    recommendation_code VARCHAR(64) NOT NULL, 
    severity VARCHAR(16) NOT NULL, 
    approval_required VARCHAR(24) NOT NULL, 
    evidence_refs JSON NOT NULL, 
    proposal_snapshot JSON NOT NULL, 
    status VARCHAR(16) DEFAULT 'open' NOT NULL, 
    decision VARCHAR(16), 
    decided_by UUID, 
    decision_note TEXT, 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    decided_at TIMESTAMP WITH TIME ZONE, 
    CONSTRAINT pk_director_decision_cases PRIMARY KEY (id), 
    CONSTRAINT ck_director_decision_cases_director_decision_case_status_valid CHECK (status IN ('open', 'approved', 'rejected', 'deferred', 'closed')), 
    CONSTRAINT ck_director_decision_cases_director_decision_case_decis_f099 CHECK (decision IS NULL OR decision IN ('approved', 'rejected', 'deferred', 'closed')), 
    CONSTRAINT ck_director_decision_cases_director_decision_case_decis_7e2a CHECK ((status = 'open' AND decision IS NULL AND decided_by IS NULL AND decided_at IS NULL) OR (status <> 'open' AND decision = status AND decided_by IS NOT NULL AND decided_at IS NOT NULL)), 
    CONSTRAINT ck_director_decision_cases_director_decision_case_sever_7989 CHECK (severity IN ('critical', 'high', 'medium', 'low', 'info')), 
    CONSTRAINT fk_director_decision_cases_project_id_projects FOREIGN KEY(project_id) REFERENCES projects (id) ON DELETE RESTRICT, 
    CONSTRAINT uq_director_decision_cases_project_key UNIQUE (project_id, case_key)
);

CREATE INDEX ix_director_decision_cases_project_status ON director_decision_cases (project_id, status, created_at);

ALTER TABLE director_decision_cases ALTER COLUMN status DROP DEFAULT;

CREATE OR REPLACE FUNCTION afs_guard_director_decision_case() RETURNS trigger AS $$
        BEGIN
          IF TG_OP = 'DELETE' THEN RAISE EXCEPTION 'director decision cases are retained for audit'; END IF;
          IF OLD.status <> 'open' THEN RAISE EXCEPTION 'director decision case disposition is one-time'; END IF;
          IF (NEW.project_id, NEW.case_key, NEW.source_brief_sha256, NEW.source_state_digest,
              NEW.recommendation_code, NEW.severity, NEW.approval_required, NEW.created_at)
             IS DISTINCT FROM
             (OLD.project_id, OLD.case_key, OLD.source_brief_sha256, OLD.source_state_digest,
              OLD.recommendation_code, OLD.severity, OLD.approval_required, OLD.created_at)
             OR to_jsonb(NEW.evidence_refs) IS DISTINCT FROM to_jsonb(OLD.evidence_refs)
             OR to_jsonb(NEW.proposal_snapshot) IS DISTINCT FROM to_jsonb(OLD.proposal_snapshot)
          THEN RAISE EXCEPTION 'director decision case proposal snapshot is immutable'; END IF;
          RETURN NEW;
        END; $$ LANGUAGE plpgsql;

CREATE TRIGGER trg_director_decision_case_immutable BEFORE UPDATE OR DELETE ON director_decision_cases FOR EACH ROW EXECUTE FUNCTION afs_guard_director_decision_case();

UPDATE alembic_version SET version_num='a41d7c2e9b60' WHERE alembic_version.version_num = '9c6e2a41b7d0';

-- Running upgrade a41d7c2e9b60 -> c7d4e9a12f60

CREATE TABLE principals (
    id UUID NOT NULL, 
    principal_kind VARCHAR(16) NOT NULL, 
    display_name VARCHAR(160) NOT NULL, 
    is_active BOOLEAN DEFAULT true NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    CONSTRAINT pk_principals PRIMARY KEY (id), 
    CONSTRAINT ck_principals_principal_kind_valid CHECK (principal_kind IN ('human', 'service'))
);

CREATE INDEX ix_principals_kind_active ON principals (principal_kind, is_active);

INSERT INTO principals (id, principal_kind, display_name, is_active, created_at)
        SELECT DISTINCT pm.principal_id, 'human', 'Legacy principal', TRUE, CURRENT_TIMESTAMP
        FROM project_members AS pm
        WHERE NOT EXISTS (SELECT 1 FROM principals p WHERE p.id = pm.principal_id);

ALTER TABLE project_members ADD CONSTRAINT fk_project_members_principal FOREIGN KEY(principal_id) REFERENCES principals (id) ON DELETE RESTRICT;

CREATE TABLE api_tokens (
    id UUID NOT NULL, 
    principal_id UUID NOT NULL, 
    token_prefix VARCHAR(20) NOT NULL, 
    token_hash VARCHAR(64) NOT NULL, 
    expires_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    revoked_at TIMESTAMP WITH TIME ZONE, 
    last_used_at TIMESTAMP WITH TIME ZONE, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    CONSTRAINT pk_api_tokens PRIMARY KEY (id), 
    CONSTRAINT ck_api_tokens_api_token_hash_length CHECK (length(token_hash) = 64), 
    CONSTRAINT fk_api_tokens_principal_id_principals FOREIGN KEY(principal_id) REFERENCES principals (id) ON DELETE CASCADE, 
    CONSTRAINT uq_api_tokens_token_prefix UNIQUE (token_prefix), 
    CONSTRAINT uq_api_tokens_token_hash UNIQUE (token_hash)
);

CREATE INDEX ix_api_tokens_principal_active ON api_tokens (principal_id, revoked_at, expires_at);

ALTER TABLE principals ALTER COLUMN is_active DROP DEFAULT;

ALTER TABLE principals ALTER COLUMN created_at DROP DEFAULT;

ALTER TABLE api_tokens ALTER COLUMN created_at DROP DEFAULT;

UPDATE alembic_version SET version_num='c7d4e9a12f60' WHERE alembic_version.version_num = 'a41d7c2e9b60';

-- Running upgrade c7d4e9a12f60 -> d9a4f2c8b710

ALTER TABLE director_decision_cases ADD COLUMN authorized_action_snapshot JSON;

CREATE TABLE action_executions (
    id UUID NOT NULL, 
    project_id UUID NOT NULL, 
    decision_case_id UUID NOT NULL, 
    action_type VARCHAR(48) NOT NULL, 
    action_sha256 VARCHAR(64) NOT NULL, 
    idempotency_key VARCHAR(160) NOT NULL, 
    status VARCHAR(16) NOT NULL, 
    requested_by UUID NOT NULL, 
    result_snapshot JSON NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    CONSTRAINT pk_action_executions PRIMARY KEY (id), 
    CONSTRAINT ck_action_executions_action_execution_status_valid CHECK (status IN ('succeeded')), 
    CONSTRAINT fk_action_executions_project_id_projects FOREIGN KEY(project_id) REFERENCES projects (id) ON DELETE RESTRICT, 
    CONSTRAINT fk_action_executions_decision_case FOREIGN KEY(decision_case_id) REFERENCES director_decision_cases (id) ON DELETE RESTRICT, 
    CONSTRAINT fk_action_executions_requested_by_principals FOREIGN KEY(requested_by) REFERENCES principals (id) ON DELETE RESTRICT, 
    CONSTRAINT uq_action_executions_project_idempotency UNIQUE (project_id, idempotency_key), 
    CONSTRAINT uq_action_executions_decision_case UNIQUE (decision_case_id)
);

CREATE INDEX ix_action_executions_project_created ON action_executions (project_id, created_at);

UPDATE alembic_version SET version_num='d9a4f2c8b710' WHERE alembic_version.version_num = 'c7d4e9a12f60';

COMMIT;

