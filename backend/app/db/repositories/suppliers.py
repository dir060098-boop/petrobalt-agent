"""
CRUD + search for suppliers table.
"""
from __future__ import annotations

import uuid
from typing import Sequence

from sqlalchemy import select, or_, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.tables import Supplier


class SuppliersRepo:
    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    # ── read ──────────────────────────────────────────────────────────────────
    async def get(self, supplier_id: uuid.UUID) -> Supplier | None:
        return await self._s.get(Supplier, supplier_id)

    async def get_by_inn(self, inn: str) -> Supplier | None:
        result = await self._s.execute(
            select(Supplier).where(Supplier.inn == inn)
        )
        return result.scalar_one_or_none()

    async def search(
        self,
        query: str | None = None,
        region: str | None = None,
        verified_only: bool = False,
        limit: int = 20,
    ) -> Sequence[Supplier]:
        """Full-text style search by name; optional region + verified filters."""
        stmt = select(Supplier)

        if query:
            # Case-insensitive LIKE on name
            stmt = stmt.where(
                func.lower(Supplier.name).contains(query.lower())
            )
        if region:
            stmt = stmt.where(
                func.lower(Supplier.region).contains(region.lower())
            )
        if verified_only:
            stmt = stmt.where(Supplier.verified.is_(True))

        stmt = stmt.order_by(Supplier.name).limit(limit)
        result = await self._s.execute(stmt)
        return result.scalars().all()

    async def list_all(self, limit: int = 100) -> Sequence[Supplier]:
        result = await self._s.execute(
            select(Supplier).order_by(Supplier.name).limit(limit)
        )
        return result.scalars().all()

    # ── write ─────────────────────────────────────────────────────────────────
    async def create(self, **kwargs) -> Supplier:
        supplier = Supplier(**kwargs)
        self._s.add(supplier)
        await self._s.flush()
        return supplier

    async def update(self, supplier: Supplier, **kwargs) -> Supplier:
        for key, value in kwargs.items():
            setattr(supplier, key, value)
        await self._s.flush()
        return supplier

    async def upsert_by_inn(self, inn: str, **kwargs) -> tuple[Supplier, bool]:
        """Return (supplier, created). Matches by INN if given."""
        existing = await self.get_by_inn(inn) if inn else None
        if existing:
            updated = await self.update(existing, **kwargs)
            return updated, False
        created = await self.create(inn=inn, **kwargs)
        return created, True
