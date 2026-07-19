import contextvars
import hashlib
import json
import logging
import time
import uuid
from collections.abc import Callable
from typing import Any


logger = logging.getLogger("heracles.observability")
request_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "request_id",
    default=None,
)


def new_request_id() -> str:
    return str(uuid.uuid4())


def anonymize_user_id(user_id: str | None) -> str | None:
    if not user_id:
        return None
    return hashlib.sha256(user_id.encode("utf-8")).hexdigest()[:16]


def log_event(event: str, **fields: Any) -> None:
    payload = {
        "event": event,
        "request_id": request_id_var.get(),
        **fields,
    }
    logger.info(json.dumps(payload, ensure_ascii=False, sort_keys=True))


async def measure_async(event: str, fn: Callable, **fields: Any):
    start = time.perf_counter()
    try:
        result = await fn()
        log_event(
            event,
            latency_ms=round((time.perf_counter() - start) * 1000, 2),
            status="ok",
            **fields,
        )
        return result
    except Exception:
        log_event(
            event,
            latency_ms=round((time.perf_counter() - start) * 1000, 2),
            status="error",
            **fields,
        )
        raise
