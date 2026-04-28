"""
Purchase requests repository.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any, Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.tables import PurchaseRequest, Quote


class PurchaseRequestsRepo:
    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    # ── read ──────────────────────────────────────────────────────────────────
    async def get(self, request_id: uuid.UUID) -> PurchaseRequest | None:
        result = await self._s.execute(
            select(PurchaseRequest)
            .where(PurchaseRequest.id == request_id)
            .options(selectinload(PurchaseRequest.quotes))
        )
        return result.scalar_one_or_none()

    async def list_by_route_card(
        self, route_card_id: uuid.UUID
    ) -> Sequence[PurchaseRequest]:
        result = await self._s.execute(
            select(PurchaseRequest)
            .where(PurchaseRequest.route_card_id == route_card_id)
            .order_by(PurchaseRequest.created_at.desc())
        )
        return result.scalars().all()

    async def list_recent(self, limit: int = 50) -> Sequence[PurchaseRequest]:
        result = await self._s.execute(
            select(PurchaseRequest)
            .order_by(PurchaseRequest.created_at.desc())
            .limit(limit)
        )
        return result.scalars().all()

    # ── write ─────────────────────────────────────────────────────────────────
    async def create(
        self,
        route_card_id: uuid.UUID | None,
        items: list[dict[str, Any]],
        notes: str | None = None,
    ) -> PurchaseRequest:
        req = PurchaseRequest(
            route_card_id=route_card_id,
            status="new",
            items=json.dumps(items, default=str),
            snapshot_at=datetime.now(timezone.utc),
            notes=notes,
        )
        self._s.add(req)
        await self._s.flush()
        return req

    async def update_status(
        self, req: PurchaseRequest, status: str
    ) -> PurchaseRequest:
        req.status = status
        await self._s.flush()
        return req

    # ── quotes ────────────────────────────────────────────────────────────────
    async def add_quote(
        self,
        purchase_request_id: uuid.UUID,
        supplier_name: str,
        total_price: float,
        lead_time_days: int,
        vat_included: bool = True,
        supplier_type: str = "unknown",
        verified: bool = False,
        score: float | None = None,
        file_url: str | None = None,
        notes: str | None = None,
        supplier_id: uuid.UUID | None = None,
    ) -> Quote:
        quote = Quote(
            purchase_request_id=purchase_request_id,
            supplier_id=supplier_id,
            supplier_name=supplier_name,
            total_price=total_price,
            lead_time_days=lead_time_days,
            vat_included=vat_included,
            supplier_type=supplier_type,
            verified=verified,
            score=score,
            file_url=file_url,
            notes=notes,
        )
        self._s.add(quote)
        await self._s.flush()
        return quote
