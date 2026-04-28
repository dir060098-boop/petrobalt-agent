"""
CRUD for materials reference table.
"""
from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Sequence

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.tables import Material


class MaterialsRepo:
    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def get(self, material_id: uuid.UUID) -> Material | None:
        return await self._s.get(Material, material_id)

    async def get_by_name(self, name: str) -> Material | None:
        result = await self._s.execute(
            select(Material).where(func.lower(Material.name) == name.lower())
        )
        return result.scalar_one_or_none()

    async def search(self, query: str, limit: int = 10) -> Sequence[Material]:
        result = await self._s.execute(
            select(Material)
            .where(func.lower(Material.name).contains(query.lower()))
            .limit(limit)
        )
        return result.scalars().all()

    async def get_waste_factor(self, material_name: str) -> Decimal | None:
        """
        Return the waste_factor stored in DB for this material, or None
        (caller falls back to keyword rules in CalculatorAgent).
        """
        mat = await self.get_by_name(material_name)
        if mat and mat.waste_factor is not None:
            return mat.waste_factor
        return None

    async def create(self, **kwargs) -> Material:
        mat = Material(**kwargs)
        self._s.add(mat)
        await self._s.flush()
        return mat

    async def get_or_create(self, name: str, **defaults) -> tuple[Material, bool]:
        existing = await self.get_by_name(name)
        if existing:
            return existing, False
        created = await self.create(name=name, **defaults)
        return created, True
