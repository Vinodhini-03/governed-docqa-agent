import json
import logging
import time
from pathlib import Path

from app.config import get_settings

log = logging.getLogger("docqa.audit")


def record(event: str, user: str, **fields) -> dict:
    entry = {"ts": time.time(), "event": event, "user": user, **fields}
    p = Path(get_settings().audit_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")
    log.info(json.dumps(entry))  # picked up by Application Insights when configured
    return entry


def tail(n: int = 50) -> list[dict]:
    p = Path(get_settings().audit_path)
    if not p.exists():
        return []
    return [json.loads(x) for x in p.read_text().splitlines()[-n:]]
