"""
Repository for route_cards and route_card_materials.
"""
from __future__ import annotations

import json
import uuid
from typing import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.tables import RouteCard, RouteCardMaterial
from app.schemas.mk_schema import MKParseResult


class RouteCardsRepo:
    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    # ── read ──────────────────────────────────────────────────────────────────
    async def get(self, card_id: uuid.UUID) -> RouteCard | None:
        result = await self._s.execute(
            select(RouteCard)
            .where(RouteCard.id == card_id)
            .options(selectinload(RouteCard.materials))
        )
        return result.scalar_one_or_none()

    async def get_by_mk_number(self, mk_number: str) -> RouteCard | None:
        result = await self._s.execute(
            select(RouteCard).where(RouteCard.mk_number == mk_number)
        )
        return result.scalar_one_or_none()

    async def list_recent(self, limit: int = 50) -> Sequence[RouteCard]:
        result = await self._s.execute(
            select(RouteCard)
            .order_by(RouteCard.created_at.desc())
            .limit(limit)
        )
        return result.scalars().all()

    # ── write ─────────────────────────────────────────────────────────────────
    async def save_parse_result(
        self,
        parse_result: MKParseResult,
        file_url: str | None = None,
    ) -> RouteCard:
        """
        Persist a fresh MKParseResult to DB, creating RouteCard + materials.
        Returns the saved RouteCard (with id).
        """
        card = RouteCard(
            mk_number=parse_result.mk_number.value,
            product_name=parse_result.product_name.value,
            quantity=(
                float(parse_result.quantity.value)
                if parse_result.quantity.value is not None
                else None
            ),
            date_start=parse_result.date_start.value,
            responsible=parse_result.responsible.value,
            status="draft",
            file_url=file_url,
            raw_data=json.dumps(parse_result.model_dump(), default=str),
        )
        self._s.add(card)
        await self._s.flush()  # get card.id

        for mat in (parse_result.planned_materials or []):
            row = RouteCardMaterial(
                route_card_id=card.id,
                position=mat.position,
                material_name=mat.material_name,
                standard=mat.standard,
                unit=mat.unit,
                qty_per_unit=float(mat.qty_per_unit) if mat.qty_per_unit else None,
            )
            self._s.add(row)

        await self._s.flush()
        return card

    async def update_status(self, card: RouteCard, status: str) -> RouteCard:
        card.status = status
        await self._s.flush()
        return card

    async def update_file_url(self, card: RouteCard, file_url: str) -> RouteCard:
        card.file_url = file_url
        await self._s.flush()
        return card
