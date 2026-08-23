import json
from typing import Any

from sqlalchemy.orm import Session

from app.models.entities import ActivityLog


def log_activity(
    db: Session,
    *,
    event_type: str,
    summary: str,
    level: int = 1,
    actor: str | None = None,
    source: str = "system",
    action: str | None = None,
    result: str = "info",
    llm_used: bool = False,
    model: str | None = None,
    estimated_cost: float = 0.0,
    details: dict[str, Any] | None = None,
) -> ActivityLog:
    item = ActivityLog(
        level=level,
        actor=actor,
        source=source,
        action=action or event_type,
        result=result,
        event_type=event_type,
        summary=summary,
        llm_used=llm_used,
        model=model,
        estimated_cost=estimated_cost,
        details=json.dumps(details or {}),
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return item
