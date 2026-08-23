import json

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.models.entities import MemoryItem


def search_memory(db: Session, query: str, limit: int = 8, owner: str | None = None) -> list[MemoryItem]:
    terms = [
        term.strip().lower()
        for term in query.split()
        if len(term.strip()) > 2 or term.strip().isdigit()
    ]
    if not terms:
        return []
    filters = []
    for term in terms:
        like = f"%{term}%"
        filters.append(MemoryItem.title.ilike(like))
        filters.append(MemoryItem.content.ilike(like))
        filters.append(MemoryItem.tags.ilike(like))

    query_set = db.query(MemoryItem).filter(or_(*filters))
    if owner:
        # A resident receives their own memories plus non-private household memory,
        # never the other resident's personal memory by accidental lexical match.
        query_set = query_set.filter(
            or_(
                MemoryItem.owner == owner,
                MemoryItem.owner.is_(None),
                MemoryItem.scope.in_(["shared", "house", "cat", "experiences", "temporary"]),
            )
        )
    return query_set.order_by(MemoryItem.created_at.desc()).limit(limit).all()


def memory_to_dict(item: MemoryItem) -> dict:
    return {
        "id": item.id,
        "scope": item.scope,
        "kind": item.kind,
        "owner": item.owner,
        "title": item.title,
        "content": item.content,
        "tags": json.loads(item.tags or "[]"),
        "source": item.source,
        "created_at": item.created_at.isoformat(),
        "expires_at": item.expires_at.isoformat() if item.expires_at else None,
    }
