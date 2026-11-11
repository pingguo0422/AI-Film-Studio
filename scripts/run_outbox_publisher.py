#!/usr/bin/env python3
"""Publish AFS transactional outbox events to a configured HTTP webhook.

Delivery is at-least-once. The receiving endpoint must deduplicate by the
idempotency_key included in every event envelope.
"""
from __future__ import annotations
import argparse
import json
import logging
import os
import signal
import threading
from pathlib import Path
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
import sys
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.app.db.session import SessionLocal
from backend.app.services.event_delivery import OutboxPublisher


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--webhook-url", default=os.getenv("AFS_OUTBOX_WEBHOOK_URL"))
    parser.add_argument("--bearer-token", default=os.getenv("AFS_OUTBOX_WEBHOOK_TOKEN"))
    parser.add_argument("--publisher-id", default=os.getenv("AFS_OUTBOX_PUBLISHER_ID", "afs-outbox-publisher-01"))
    parser.add_argument("--lease-seconds", type=int, default=30)
    parser.add_argument("--poll-interval", type=float, default=0.5)
    parser.add_argument("--timeout-seconds", type=float, default=15.0)
    parser.add_argument("--max-events", type=int, default=None)
    args = parser.parse_args()
    if not args.webhook_url:
        parser.error("set AFS_OUTBOX_WEBHOOK_URL or pass --webhook-url")
    if args.timeout_seconds <= 0 or args.poll_interval <= 0:
        parser.error("timeout and poll interval must be positive")

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

    def publish(envelope: dict) -> None:
        headers = {"Content-Type": "application/json", "Idempotency-Key": envelope["idempotency_key"]}
        if args.bearer_token:
            headers["Authorization"] = f"Bearer {args.bearer_token}"
        request = Request(args.webhook_url, data=json.dumps(envelope).encode("utf-8"), headers=headers, method="POST")
        with urlopen(request, timeout=args.timeout_seconds) as response:
            if not 200 <= response.status < 300:
                raise RuntimeError(f"webhook returned HTTP {response.status}")

    publisher = OutboxPublisher(session_factory=SessionLocal, publisher_id=args.publisher_id,
                                publish=publish, lease_seconds=args.lease_seconds)
    stop = threading.Event()
    def request_stop(_signum, _frame):
        logging.getLogger(__name__).info("shutdown requested")
        stop.set()
    signal.signal(signal.SIGINT, request_stop)
    signal.signal(signal.SIGTERM, request_stop)
    count = publisher.run_forever(stop_event=stop, idle_sleep_seconds=args.poll_interval, max_events=args.max_events)
    logging.getLogger(__name__).info("outbox publisher stopped", extra={"published_or_attempted": count})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
