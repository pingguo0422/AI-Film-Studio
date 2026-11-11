#!/usr/bin/env python3
"""Import/export the real Heaven Ship 8.1 Footage-Mode package into AFS DB."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from uuid import UUID

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.app.db.session import SessionLocal
from integrations.footage_mode.persistence import (
    export_run_bundle,
    import_coverage_documents,
    load_heaven_ship_81_documents,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, required=True, help="Footage-Mode 2.2-B ZIP")
    parser.add_argument("--project-id", type=UUID, required=True, help="Existing AFS project UUID")
    parser.add_argument("--idempotency-key", required=True, help="Stable key for this import request")
    parser.add_argument("--export", type=Path, help="Optional path for exporting the persisted run bundle")
    args = parser.parse_args()

    coverage, events = load_heaven_ship_81_documents(args.archive)
    with SessionLocal() as db:
        run_id = import_coverage_documents(
            db,
            project_id=args.project_id,
            archive_path=args.archive,
            coverage_document=coverage,
            events_document=events,
            idempotency_key=args.idempotency_key,
        )
        result = {"status": "persisted", "integration_run_id": str(run_id), "events": len(events["events"]), "coverage_decisions": len(coverage["event_decisions"])}
        if args.export:
            bundle = export_run_bundle(db, integration_run_id=run_id)
            args.export.parent.mkdir(parents=True, exist_ok=True)
            with args.export.open("x", encoding="utf-8") as stream:
                json.dump(bundle, stream, ensure_ascii=False, indent=2)
                stream.write("\n")
            result["export_path"] = str(args.export)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
