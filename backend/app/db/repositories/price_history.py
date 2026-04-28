"""
Price history — latest price lookup for CalculatorAgent default costs.
"""
from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.tables import Material, PriceHistory


class PriceHistoryRepo:
    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def get_latest_price(
        self,
        material_name: str,
        supplier_id: uuid.UUID | None = None,
        as_of: date | None = None,
    ) -> Decimal | None:
        """
        Return the most recent unit price for a material.
        Falls back to None so CalculatorAgent can leave unit_price blank.
        """
        stmt = (
            select(PriceHistory)
            .join(Material, PriceHistory.material_id == Material.id)
            .where(Material.name.ilike(f"%{material_name}%"))
        )
        if supplier_id:
            stmt = stmt.where(PriceHistory.supplier_id == supplier_id)
        if as_of:
            stmt = stmt.where(
                (PriceHistory.valid_from.is_(None)) | (PriceHistory.valid_from <= as_of)
            ).where(
                (PriceHistory.valid_to.is_(None)) | (PriceHistory.valid_to >= as_of)
            )
        stmt = stmt.order_by(desc(PriceHistory.created_at)).limit(1)

        result = await self._s.execute(stmt)
        row = result.scalar_one_or_none()
        return row.price if row else None

    async def add(
        self,
        material_id: uuid.UUID,
        price: Decimal,
        supplier_id: uuid.UUID | None = None,
        currency: str = "RUB",
        unit: str | None = None,
        valid_from: date | None = None,
        valid_to: date | None = None,
        source: str | None = None,
    ) -> PriceHistory:
        row = PriceHistory(
            material_id=material_id,
            supplier_id=supplier_id,
            price=price,
            currency=currency,
            unit=unit,
            valid_from=valid_from,
            valid_to=valid_to,
            source=source,
        )
        self._s.add(row)
        await self._s.flush()
        return row
