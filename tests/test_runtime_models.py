import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session
from backend.app.db.base import Base
from backend.app.db.ids import uuid7
from backend.app.models import Project, Agent, AgentVersion, Skill, SkillVersion, ModelProvider, Model, ModelProviderDeployment, Task, AgentRun, SkillRun, ModelRun, OutboxEvent, InboxEvent
from backend.app.services.task_service import add_task_dependency, TaskDependencyCycleError

def make_db():
    engine=create_engine("sqlite+pysqlite:///:memory:")
    @event.listens_for(engine,"connect")
    def fk(dbapi_connection,_): dbapi_connection.execute("PRAGMA foreign_keys=ON")
    Base.metadata.create_all(engine)
    return engine

def test_runtime_registry_and_run_snapshots_create():
    engine=make_db(); p=uuid7(); a=uuid7(); av=uuid7(); s=uuid7(); sv=uuid7(); provider=uuid7(); model=uuid7(); dep=uuid7(); task=uuid7(); run=uuid7(); sr=uuid7(); mr=uuid7()
    with Session(engine) as db:
        db.add(Project(id=p,code="PRJ_RUNTIME",name="Runtime")); db.flush()
        db.add_all([Agent(id=a,code="EXEC_DIRECTOR",display_name="Executive Director"), Skill(id=s,code="SCRIPT_ANALYSIS",display_name="Script Analysis"), ModelProvider(id=provider,code="provider_x",display_name="Provider X"), Model(id=model,model_key="text-model-x",modality="text",capabilities={})]); db.flush()
        db.add_all([AgentVersion(id=av,agent_id=a,version_number=1,definition_snapshot={"role":"director"},definition_sha256="a"*64),SkillVersion(id=sv,skill_id=s,version_number=1,definition_snapshot={"skill":"analysis"},definition_sha256="b"*64)]); db.flush()
        db.add(ModelProviderDeployment(id=dep,provider_id=provider,model_id=model,deployment_key="deploy-x",config_snapshot={"credential_ref":"vault://afs/provider-x"})); db.flush()
        db.add(Task(id=task,project_id=p,task_type="SCRIPT_REVIEW",title="Review",input_snapshot={})); db.flush()
        db.add(AgentRun(id=run,project_id=p,task_id=task,agent_id=a,agent_version_id=av,input_snapshot={"task":"review"})); db.flush()
        db.add(SkillRun(id=sr,project_id=p,agent_run_id=run,skill_id=s,skill_version_id=sv,input_snapshot={})); db.flush()
        db.add(ModelRun(id=mr,project_id=p,agent_run_id=run,skill_run_id=sr,model_id=model,deployment_id=dep,request_snapshot={})); db.flush()
        db.add(OutboxEvent(aggregate_type="task",aggregate_id=task,event_type="task.created",idempotency_key="task-created-1",payload={}))
        db.add(InboxEvent(consumer_key="agent-runtime",idempotency_key="event-1",event_type="task.created",payload={}))
        db.commit()

def test_task_dependency_service_rejects_cycle():
    engine=make_db(); p=uuid7(); a=uuid7(); b=uuid7(); c=uuid7()
    with Session(engine) as db:
        db.add(Project(id=p,code="PRJ_DAG",name="DAG")); db.flush()
        db.add_all([Task(id=a,project_id=p,task_type="A",title="A",input_snapshot={}),Task(id=b,project_id=p,task_type="B",title="B",input_snapshot={}),Task(id=c,project_id=p,task_type="C",title="C",input_snapshot={})]); db.flush()
        add_task_dependency(db,project_id=p,task_id=a,depends_on_task_id=b)
        add_task_dependency(db,project_id=p,task_id=b,depends_on_task_id=c)
        with pytest.raises(TaskDependencyCycleError):
            add_task_dependency(db,project_id=p,task_id=c,depends_on_task_id=a)
