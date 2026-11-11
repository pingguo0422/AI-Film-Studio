"""At-least-once Outbox delivery and transactional Inbox consumption.

The publisher intentionally acknowledges only after the external publish callback
returns. A crash between external delivery and acknowledgement can redeliver; every
envelope therefore carries the stable idempotency_key. Consumers should deduplicate.
"""
from __future__ import annotations
import logging
import threading
from datetime import datetime, timedelta, timezone
from typing import Callable
from uuid import uuid4
from sqlalchemy import or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session, sessionmaker
from backend.app.models import OutboxEvent, InboxEvent

logger = logging.getLogger(__name__)


def reap_expired_outbox_claims(db: Session, *, now: datetime | None = None) -> int:
    """Recover expired publisher claims; exhausted crash-loop claims become dead."""
    now = now or datetime.now(timezone.utc)
    rows = db.scalars(select(OutboxEvent).where(
        OutboxEvent.status == "publishing", OutboxEvent.claim_expires_at <= now,
    ).with_for_update(skip_locked=True)).all()
    for row in rows:
        row.claimed_by = row.claim_token = None
        row.claim_expires_at = None
        if row.attempt_count >= row.max_attempts:
            row.status = "dead"
            row.next_attempt_at = None
            row.last_error = row.last_error or {"code": "PUBLISHER_LEASE_EXHAUSTED", "message": "publisher claim expired after maximum attempts"}
        else:
            row.status = "pending"
            row.next_attempt_at = now
    db.flush()
    return len(rows)


def claim_outbox_event(db: Session, *, publisher_id: str, lease_seconds: int = 30,
                       now: datetime | None = None) -> tuple[OutboxEvent, str] | None:
    if not publisher_id or len(publisher_id) > 128:
        raise ValueError("publisher_id must be 1-128 characters")
    if not isinstance(lease_seconds, int) or isinstance(lease_seconds, bool) or not 1 <= lease_seconds <= 3600:
        raise ValueError("lease_seconds must be 1-3600")
    now = now or datetime.now(timezone.utc)
    reap_expired_outbox_claims(db, now=now)
    ready = or_(
        (OutboxEvent.status == "pending") & (or_(OutboxEvent.next_attempt_at.is_(None), OutboxEvent.next_attempt_at <= now)),
        (OutboxEvent.status == "publishing") & (OutboxEvent.claim_expires_at <= now),
    )
    row = db.scalar(select(OutboxEvent).where(ready).order_by(OutboxEvent.created_at.asc())
                    .with_for_update(skip_locked=True).limit(1))
    if row is None:
        return None
    token = str(uuid4())
    row.status = "publishing"
    row.claimed_by = publisher_id
    row.claim_token = token
    row.claim_expires_at = now + timedelta(seconds=lease_seconds)
    row.attempt_count += 1
    db.flush()
    return row, token


def _validate_claim(row: OutboxEvent | None, claim_token: str, now: datetime) -> OutboxEvent:
    if row is None or row.status != "publishing" or row.claim_token != claim_token:
        raise RuntimeError("outbox claim is missing or no longer owned by this publisher")
    expiry = row.claim_expires_at
    if expiry is not None and expiry.tzinfo is None:
        expiry = expiry.replace(tzinfo=timezone.utc)
    if expiry is None or expiry <= now:
        raise RuntimeError("outbox claim has expired")
    return row


def acknowledge_outbox_event(db: Session, *, event_id, claim_token: str,
                             now: datetime | None = None) -> OutboxEvent:
    now = now or datetime.now(timezone.utc)
    row = db.scalar(select(OutboxEvent).where(OutboxEvent.id == event_id).with_for_update())
    row = _validate_claim(row, claim_token, now)
    row.status = "published"
    row.published_at = now
    row.claimed_by = row.claim_token = None
    row.claim_expires_at = None
    row.last_error = None
    db.flush()
    return row


def fail_outbox_event(db: Session, *, event_id, claim_token: str, error: Exception,
                      now: datetime | None = None, base_delay_seconds: int = 2,
                      max_delay_seconds: int = 900) -> OutboxEvent:
    now = now or datetime.now(timezone.utc)
    row = db.scalar(select(OutboxEvent).where(OutboxEvent.id == event_id).with_for_update())
    row = _validate_claim(row, claim_token, now)
    row.last_error = {"type": type(error).__name__, "message": str(error)[:2000]}
    row.claimed_by = row.claim_token = None
    row.claim_expires_at = None
    if row.attempt_count >= row.max_attempts:
        row.status = "dead"
        row.next_attempt_at = None
    else:
        delay = min(max_delay_seconds, base_delay_seconds * (2 ** max(0, row.attempt_count - 1)))
        row.status = "pending"
        row.next_attempt_at = now + timedelta(seconds=delay)
    db.flush()
    return row


class OutboxPublisher:
    def __init__(self, *, session_factory: sessionmaker[Session], publisher_id: str,
                 publish: Callable[[dict], None], lease_seconds: int = 30):
        self.session_factory = session_factory
        self.publisher_id = publisher_id
        self.publish = publish
        self.lease_seconds = lease_seconds

    def publish_once(self) -> dict | None:
        with self.session_factory() as db:
            claimed = claim_outbox_event(db, publisher_id=self.publisher_id, lease_seconds=self.lease_seconds)
            if claimed is None:
                db.commit()
                return None
            row, token = claimed
            envelope = {"event_id": str(row.id), "aggregate_type": row.aggregate_type,
                "aggregate_id": str(row.aggregate_id), "event_type": row.event_type,
                "idempotency_key": row.idempotency_key, "payload": dict(row.payload)}
            event_id = row.id
            db.commit()
        try:
            self.publish(envelope)
        except Exception as exc:
            with self.session_factory() as db:
                fail_outbox_event(db, event_id=event_id, claim_token=token, error=exc)
                db.commit()
            logger.exception("outbox publish failed", extra={"event_id": str(event_id)})
            return {"event_id": str(event_id), "status": "retry_or_dead"}
        with self.session_factory() as db:
            acknowledge_outbox_event(db, event_id=event_id, claim_token=token)
            db.commit()
        return {"event_id": str(event_id), "status": "published"}

    def run_forever(self, *, stop_event: threading.Event | None = None,
                    idle_sleep_seconds: float = 0.5, max_events: int | None = None) -> int:
        if idle_sleep_seconds <= 0:
            raise ValueError("idle_sleep_seconds must be positive")
        stop = stop_event or threading.Event()
        count = 0
        while not stop.is_set() and (max_events is None or count < max_events):
            try:
                result = self.publish_once()
            except Exception:
                logger.exception("outbox publisher iteration failed", extra={"publisher_id": self.publisher_id})
                stop.wait(idle_sleep_seconds)
                continue
            if result is None:
                stop.wait(idle_sleep_seconds)
            else:
                count += 1
        return count


class InboxConsumer:
    """Runs handler and inbox acknowledgement in one database transaction."""
    def __init__(self, *, session_factory: sessionmaker[Session], consumer_key: str,
                 handlers: dict[str, Callable[[Session, dict], None]]):
        if not consumer_key or len(consumer_key) > 96:
            raise ValueError("consumer_key must be 1-96 characters")
        self.session_factory = session_factory
        self.consumer_key = consumer_key
        self.handlers = dict(handlers)

    def consume(self, envelope: dict) -> dict:
        required = {"idempotency_key", "event_type", "payload"}
        if not isinstance(envelope, dict) or not required.issubset(envelope):
            raise ValueError("event envelope is missing required fields")
        if not isinstance(envelope["payload"], dict):
            raise ValueError("event payload must be an object")
        handler = self.handlers.get(envelope["event_type"])
        if handler is None:
            raise LookupError(f"no handler registered for {envelope['event_type']}")
        with self.session_factory() as db:
            with db.begin():
                dialect = db.get_bind().dialect.name
                values = {
                    "consumer_key": self.consumer_key,
                    "idempotency_key": envelope["idempotency_key"],
                    "event_type": envelope["event_type"],
                    "payload": dict(envelope["payload"]),
                }
                if dialect == "postgresql":
                    insert_stmt = pg_insert(InboxEvent).values(**values)
                elif dialect == "sqlite":
                    insert_stmt = sqlite_insert(InboxEvent).values(**values)
                else:
                    raise RuntimeError(f"InboxConsumer does not support dialect: {dialect}")
                inserted_id = db.scalar(insert_stmt.on_conflict_do_nothing(
                    index_elements=[InboxEvent.consumer_key, InboxEvent.idempotency_key]
                ).returning(InboxEvent.id))
                created = inserted_id is not None
                if created:
                    row = db.scalar(select(InboxEvent).where(InboxEvent.id == inserted_id).with_for_update())
                else:
                    row = db.scalar(select(InboxEvent).where(
                        InboxEvent.consumer_key == self.consumer_key,
                        InboxEvent.idempotency_key == envelope["idempotency_key"],
                    ).with_for_update())
                    if row is None:
                        # A concurrent transaction may have rolled back after a conflict wait.
                        raise RuntimeError("inbox conflict row disappeared; retry delivery")
                    if row.event_type != envelope["event_type"] or row.payload != envelope["payload"]:
                        raise ValueError("inbox idempotency key conflicts with existing event")
                    if row.status == "processed":
                        return {"status": "duplicate", "inbox_id": str(row.id)}
                handler(db, dict(envelope["payload"]))
                row.status = "processed"
                row.processed_at = datetime.now(timezone.utc)
                db.flush()
                return {"status": "processed" if created else "reprocessed", "inbox_id": str(row.id)}
