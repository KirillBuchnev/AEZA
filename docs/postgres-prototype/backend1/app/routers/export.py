from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy import text
from ..exporters import export
from ..state import database, require_session

router = APIRouter(prefix="/api/v1/export", tags=["export"])
ENTITIES = {
    "customers": ["id", "email", "balance_minor", "withdraw_balance_minor", "bonus_balance_minor", "bonus_spend_enabled", "total_replenished_minor"],
    "services": ["id", "customer_id", "name", "price_minor", "auto_prolong", "payment_term", "status", "expires_at"],
    "transactions": ["id", "customer_id", "service_id", "status", "type", "amount_minor", "created_at"],
    "sessions": ["token_hash", "username", "expires_at", "created_at"],
    "login_attempts": ["client_key", "window_started_at", "failures"],
    "app_state": ["key", "value"],
}

@router.get("/{entity}")
def export_entity(entity: str, format: str = Query("csv", pattern="^(csv|xlsx|xml)$"), _: str = Depends(require_session)) -> Response:
    fields = ENTITIES.get(entity)
    if not fields: raise HTTPException(404, f"Неизвестная сущность: {entity}. Доступно: {', '.join(ENTITIES)}")
    with database.connection() as s:
        rows = s.execute(text(f'SELECT {", ".join(fields)} FROM {entity} ORDER BY 1')).mappings().all()
    data, mime, filename = export([dict(r) for r in rows], fields, format, entity)
    return Response(content=data, media_type=mime, headers={"Content-Disposition": f'attachment; filename="{filename}"'})