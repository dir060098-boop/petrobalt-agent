"""
SQLAlchemy ORM models — отражают schema.sql v2.2.

NOTE: Python 3.9 — SQLAlchemy evaluates Mapped[] at class-creation time,
so we use Optional[X] instead of X | None in all Mapped[] annotations.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import List, Optional

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


# ─────────────────────────────────────────────────────────────────────────────
# route_cards (МК / маршрутные карты)
# ─────────────────────────────────────────────────────────────────────────────
class RouteCard(Base):
    __tablename__ = "route_cards"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    mk_number: Mapped[Optional[str]] = mapped_column(String(100))
    product_name: Mapped[Optional[str]] = mapped_column(Text)
    quantity: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 3))
    date_start: Mapped[Optional[date]] = mapped_column(Date)
    responsible: Mapped[Optional[str]] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(50), default="draft")
    file_url: Mapped[Optional[str]] = mapped_column(Text)
    raw_data: Mapped[Optional[str]] = mapped_column(Text)   # JSON string
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    materials: Mapped[List[RouteCardMaterial]] = relationship(
        back_populates="route_card", cascade="all, delete-orphan"
    )
    purchase_requests: Mapped[List[PurchaseRequest]] = relationship(
        back_populates="route_card", cascade="all, delete-orphan"
    )


# ─────────────────────────────────────────────────────────────────────────────
# route_card_materials
# ─────────────────────────────────────────────────────────────────────────────
class RouteCardMaterial(Base):
    __tablename__ = "route_card_materials"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    route_card_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("route_cards.id", ondelete="CASCADE")
    )
    position: Mapped[Optional[int]] = mapped_column(Integer)
    material_name: Mapped[Optional[str]] = mapped_column(Text)
    standard: Mapped[Optional[str]] = mapped_column(String(255))
    unit: Mapped[Optional[str]] = mapped_column(String(50))
    qty_per_unit: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 4))
    qty_required: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 4))
    qty_to_purchase: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 4))
    waste_factor: Mapped[Optional[Decimal]] = mapped_column(Numeric(6, 4))

    route_card: Mapped[RouteCard] = relationship(back_populates="materials")


# ─────────────────────────────────────────────────────────────────────────────
# suppliers
# ─────────────────────────────────────────────────────────────────────────────
class Supplier(Base):
    __tablename__ = "suppliers"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    inn: Mapped[Optional[str]] = mapped_column(String(12), unique=True)
    type: Mapped[str] = mapped_column(
        String(50), default="unknown"
    )  # manufacturer / distributor / trader / unknown
    region: Mapped[Optional[str]] = mapped_column(String(100))
    contacts: Mapped[Optional[str]] = mapped_column(Text)  # JSON
    verified: Mapped[bool] = mapped_column(Boolean, default=False)
    vat_registered: Mapped[bool] = mapped_column(Boolean, default=True)
    rating: Mapped[Optional[Decimal]] = mapped_column(Numeric(3, 2))
    notes: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    price_history: Mapped[List[PriceHistory]] = relationship(back_populates="supplier")
    quotes: Mapped[List[Quote]] = relationship(back_populates="supplier")


# ─────────────────────────────────────────────────────────────────────────────
# materials (справочник материалов)
# ─────────────────────────────────────────────────────────────────────────────
class Material(Base):
    __tablename__ = "materials"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    aliases: Mapped[Optional[str]] = mapped_column(Text)  # JSON array
    category: Mapped[Optional[str]] = mapped_column(String(100))
    unit: Mapped[Optional[str]] = mapped_column(String(50))
    waste_factor: Mapped[Optional[Decimal]] = mapped_column(Numeric(6, 4))
    notes: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    __table_args__ = (UniqueConstraint("name", name="uq_materials_name"),)

    stock_balances: Mapped[List[StockBalance]] = relationship(
        back_populates="material"
    )
    price_history: Mapped[List[PriceHistory]] = relationship(
        back_populates="material"
    )


# ─────────────────────────────────────────────────────────────────────────────
# stock_balances
# ─────────────────────────────────────────────────────────────────────────────
class StockBalance(Base):
    __tablename__ = "stock_balances"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    material_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("materials.id", ondelete="CASCADE")
    )
    warehouse: Mapped[Optional[str]] = mapped_column(String(100))
    quantity: Mapped[Decimal] = mapped_column(Numeric(14, 4), default=Decimal("0"))
    unit: Mapped[Optional[str]] = mapped_column(String(50))
    reserved: Mapped[Decimal] = mapped_column(Numeric(14, 4), default=Decimal("0"))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    material: Mapped[Material] = relationship(back_populates="stock_balances")


# ─────────────────────────────────────────────────────────────────────────────
# price_history
# ─────────────────────────────────────────────────────────────────────────────
class PriceHistory(Base):
    __tablename__ = "price_history"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    material_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("materials.id", ondelete="CASCADE")
    )
    supplier_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("suppliers.id", ondelete="SET NULL")
    )
    price: Mapped[Decimal] = mapped_column(Numeric(14, 4), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="RUB")
    unit: Mapped[Optional[str]] = mapped_column(String(50))
    valid_from: Mapped[Optional[date]] = mapped_column(Date)
    valid_to: Mapped[Optional[date]] = mapped_column(Date)
    source: Mapped[Optional[str]] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    material: Mapped[Material] = relationship(back_populates="price_history")
    supplier: Mapped[Optional[Supplier]] = relationship(back_populates="price_history")


# ─────────────────────────────────────────────────────────────────────────────
# purchase_requests
# ─────────────────────────────────────────────────────────────────────────────
class PurchaseRequest(Base):
    __tablename__ = "purchase_requests"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    route_card_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("route_cards.id", ondelete="SET NULL")
    )
    status: Mapped[str] = mapped_column(String(50), default="new")
    # new / rfq_sent / quotes_received / approved / ordered / delivered / cancelled
    items: Mapped[Optional[str]] = mapped_column(Text)   # JSON array of line items
    snapshot_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    notes: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    route_card: Mapped[Optional[RouteCard]] = relationship(
        back_populates="purchase_requests"
    )
    quotes: Mapped[List[Quote]] = relationship(
        back_populates="purchase_request", cascade="all, delete-orphan"
    )


# ─────────────────────────────────────────────────────────────────────────────
# quotes (КП — коммерческие предложения)
# ─────────────────────────────────────────────────────────────────────────────
class Quote(Base):
    __tablename__ = "quotes"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    purchase_request_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("purchase_requests.id", ondelete="SET NULL")
    )
    supplier_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("suppliers.id", ondelete="SET NULL")
    )
    supplier_name: Mapped[Optional[str]] = mapped_column(String(255))  # denormalized
    total_price: Mapped[Optional[Decimal]] = mapped_column(Numeric(16, 4))
    currency: Mapped[str] = mapped_column(String(3), default="RUB")
    lead_time_days: Mapped[Optional[int]] = mapped_column(Integer)
    vat_included: Mapped[bool] = mapped_column(Boolean, default=True)
    supplier_type: Mapped[str] = mapped_column(String(50), default="unknown")
    verified: Mapped[bool] = mapped_column(Boolean, default=False)
    score: Mapped[Optional[Decimal]] = mapped_column(Numeric(5, 4))
    file_url: Mapped[Optional[str]] = mapped_column(Text)
    notes: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    purchase_request: Mapped[Optional[PurchaseRequest]] = relationship(
        back_populates="quotes"
    )
    supplier: Mapped[Optional[Supplier]] = relationship(back_populates="quotes")
