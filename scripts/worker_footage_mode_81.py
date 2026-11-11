#!/usr/bin/env python3
"""Run a persistent AFS Worker for the Heaven Ship 8.1 Footage-Mode Skill."""
from __future__ import annotations

import argparse
import logging
import signal
import sys
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
for item in (str(ROOT), str(SCRIPTS)):
    if item not in sys.path:
        sys.path.insert(0, item)

from backend.app.db.session import SessionLocal
from backend.app.runtime.worker import SkillRegistration, Worker
from integrations.footage_mode.skill import build_heaven_ship_81_validation_executor
from run_footage_mode_81_agent import ensure_registry


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, default=ROOT / "source-baseline" / "Footage-Mode-2.2-B.zip")
    parser.add_argument("--worker-id", default="afs-footage-mode-worker-01")
    parser.add_argument("--lease-seconds", type=int, default=120)
    parser.add_argument("--heartbeat-interval", type=float, default=30.0)
    parser.add_argument("--poll-interval", type=float, default=1.0)
    parser.add_argument("--max-tasks", type=int, default=None, help="Exit after this many completed tasks; default runs continuously")
    args = parser.parse_args()
    if not args.archive.is_file():
        parser.error(f"Footage-Mode archive not found: {args.archive}")

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    with SessionLocal() as db:
        agent, agent_version, _skill, skill_version = ensure_registry(db)
        db.commit()

    executor = build_heaven_ship_81_validation_executor(session_factory=SessionLocal, archive_path=args.archive)
    worker = Worker(
        session_factory=SessionLocal,
        worker_id=args.worker_id,
        registrations=[SkillRegistration(
            task_type="FOOTAGE_MODE_81_SOURCE_VALIDATION",
            agent_id=agent.id,
            agent_version_id=agent_version.id,
            skill_version_id=skill_version.id,
            executor=executor,
        )],
        lease_seconds=args.lease_seconds,
        heartbeat_interval_seconds=args.heartbeat_interval,
    )
    stop = threading.Event()
    def request_stop(_signum, _frame):
        logging.getLogger(__name__).info("shutdown requested; finishing current task")
        stop.set()
    signal.signal(signal.SIGINT, request_stop)
    signal.signal(signal.SIGTERM, request_stop)
    processed = worker.run_forever(stop_event=stop, idle_sleep_seconds=args.poll_interval, max_tasks=args.max_tasks)
    logging.getLogger(__name__).info("worker stopped", extra={"processed_tasks": processed})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
