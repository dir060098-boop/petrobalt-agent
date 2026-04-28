"""
Stock balance queries — used by CalculatorAgent to check on-hand inventory.
"""
from __future__ import annotations

import uuid
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.tables import Material, StockBalance


class StockBalancesRepo:
    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def get_available(
        self,
        material_name: str,
        warehouse: str | None = None,
    ) -> Decimal:
        """
        Return quantity - reserved for the given material name.
        Returns Decimal("0") if no record found.
        """
        # Join through materials to find by name
        stmt = (
            select(StockBalance)
            .join(Material, StockBalance.material_id == Material.id)
            .where(
                Material.name.ilike(f"%{material_name}%")
            )
        )
        if warehouse:
            stmt = stmt.where(StockBalance.warehouse == warehouse)

        result = await self._s.execute(stmt)
        rows = result.scalars().all()

        if not rows:
            return Decimal("0")

        # Sum across all matching warehouses (or single match)
        total = sum((r.quantity - r.reserved for r in rows), Decimal("0"))
        return max(total, Decimal("0"))

    async def get_by_material_id(
        self, material_id: uuid.UUID, warehouse: str | None = None
    ) -> list[StockBalance]:
        stmt = select(StockBalance).where(
            StockBalance.material_id == material_id
        )
        if warehouse:
            stmt = stmt.where(StockBalance.warehouse == warehouse)
        result = await self._s.execute(stmt)
        return list(result.scalars().all())

    async def upsert(
        self,
        material_id: uuid.UUID,
        quantity: Decimal,
        warehouse: str = "main",
        unit: str | None = None,
    ) -> StockBalance:
        """Insert or update stock balance for material + warehouse."""
        result = await self._s.execute(
            select(StockBalance).where(
                StockBalance.material_id == material_id,
                StockBalance.warehouse == warehouse,
            )
        )
        row = result.scalar_one_or_none()
        if row:
            row.quantity = quantity
            row.unit = unit or row.unit
        else:
            row = StockBalance(
                material_id=material_id,
                quantity=quantity,
                warehouse=warehouse,
                unit=unit,
            )
            self._s.add(row)
        await self._s.flush()
        return row

    async def reserve(
        self,
        material_id: uuid.UUID,
        amount: Decimal,
        warehouse: str = "main",
    ) -> bool:
        """
        Mark `amount` as reserved. Returns False if not enough available.
        """
        result = await self._s.execute(
            select(StockBalance).where(
                StockBalance.material_id == material_id,
                StockBalance.warehouse == warehouse,
            )
        )
        row = result.scalar_one_or_none()
        if not row:
            return False
        available = row.quantity - row.reserved
        if available < amount:
            return False
        row.reserved += amount
        await self._s.flush()
        return True
