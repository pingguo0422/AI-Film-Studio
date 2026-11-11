#!/usr/bin/env python3
"""Run the registered AFS agent + Footage-Mode 8.1 validation Skill on one project task."""
from __future__ import annotations
import argparse, hashlib, json, sys
from pathlib import Path
from uuid import UUID
ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path: sys.path.insert(0,str(ROOT))
from sqlalchemy import select
from backend.app.db.ids import uuid7
from backend.app.db.session import SessionLocal
from backend.app.models import (Project,Agent,AgentVersion,AgentVersionPointer,Skill,SkillVersion,SkillVersionPointer,AgentSkillBinding)
from backend.app.services.task_service import create_task
from backend.app.services.orchestrator import execute_one_skill_task
from integrations.footage_mode.skill import build_heaven_ship_81_validation_executor


def digest(value: dict) -> str:
    return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(",",":")).encode()).hexdigest()


def ensure_registry(db):
    agent=db.scalar(select(Agent).where(Agent.code=="AI_EXECUTIVE_DIRECTOR"))
    if agent is None:
        agent=Agent(code="AI_EXECUTIVE_DIRECTOR",display_name="AI Executive Director"); db.add(agent); db.flush()
    avp=db.scalar(select(AgentVersionPointer).where(AgentVersionPointer.agent_id==agent.id))
    av=db.get(AgentVersion,avp.active_version_id) if avp and avp.active_version_id else None
    if av is None:
        definition={"role":"executive_director","runtime":"AFS provider-neutral deterministic orchestrator","decision_authority":"propose_and_coordinate_only","model_calls_enabled":False}
        versions=db.scalars(select(AgentVersion).where(AgentVersion.agent_id==agent.id)).all()
        av=AgentVersion(agent_id=agent.id,version_number=max([v.version_number for v in versions],default=0)+1,
                        definition_snapshot=definition,definition_sha256=digest(definition))
        db.add(av); db.flush()
        if avp is None: avp=AgentVersionPointer(agent_id=agent.id); db.add(avp)
        avp.active_version_id=av.id
    skill=db.scalar(select(Skill).where(Skill.code=="FOOTAGE_MODE_81_VALIDATION"))
    if skill is None:
        skill=Skill(code="FOOTAGE_MODE_81_VALIDATION",display_name="Footage-Mode 8.1 Source Validation"); db.add(skill); db.flush()
    svp=db.scalar(select(SkillVersionPointer).where(SkillVersionPointer.skill_id==skill.id))
    sv=db.get(SkillVersion,svp.active_version_id) if svp and svp.active_version_id else None
    if sv is None:
        definition={"skill":"footage_mode_8_1_source_validation_and_import","package":"Footage-Mode 2.2-B recovered","input":"project_id + task_id","model_calls_enabled":False,"human_approval":"never_auto_approve"}
        versions=db.scalars(select(SkillVersion).where(SkillVersion.skill_id==skill.id)).all()
        sv=SkillVersion(skill_id=skill.id,version_number=max([v.version_number for v in versions],default=0)+1,
                        definition_snapshot=definition,definition_sha256=digest(definition))
        db.add(sv); db.flush()
        if svp is None: svp=SkillVersionPointer(skill_id=skill.id); db.add(svp)
        svp.active_version_id=sv.id
    binding=db.scalar(select(AgentSkillBinding).where(AgentSkillBinding.agent_version_id==av.id,AgentSkillBinding.skill_version_id==sv.id))
    if binding is None: db.add(AgentSkillBinding(agent_version_id=av.id,skill_version_id=sv.id,binding_config={"executor":"integrations.footage_mode.skill"}))
    db.flush()
    return agent,av,skill,sv


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-id",type=UUID,required=True)
    parser.add_argument("--archive",type=Path,default=ROOT/"source-baseline"/"Footage-Mode-2.2-B.zip")
    parser.add_argument("--idempotency-key",required=True)
    parser.add_argument("--worker-id",default="afs-local-worker")
    args=parser.parse_args()
    if not args.archive.is_file(): parser.error(f"archive not found: {args.archive}")
    with SessionLocal() as db:
        project=db.get(Project,args.project_id)
        if project is None: parser.error("project-id does not exist in configured AFS database")
        agent,av,skill,sv=ensure_registry(db)
        task=create_task(db,project_id=project.id,task_type="FOOTAGE_MODE_81_SOURCE_VALIDATION",
            title="《天堂号》8.1 Footage-Mode source validation/import",input_snapshot={"project_id":str(project.id)},
            idempotency_key=args.idempotency_key)
        db.commit()
        executor=build_heaven_ship_81_validation_executor(session_factory=SessionLocal,archive_path=args.archive)
        result=execute_one_skill_task(db,worker_id=args.worker_id,agent_id=agent.id,agent_version_id=av.id,
            skill_version_id=sv.id,executor=executor,task_id=task.id)
        db.commit()
        print(json.dumps({"task_id":str(task.id),"agent_id":str(agent.id),"agent_version_id":str(av.id),
            "skill_id":str(skill.id),"skill_version_id":str(sv.id),"execution":result},ensure_ascii=False,indent=2))
        return 0 if result and result.get("status")=="succeeded" else 2

if __name__=="__main__": raise SystemExit(main())
