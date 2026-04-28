"""initial_schema

Revision ID: fb2f9df4bc0b
Revises:
Create Date: 2026-04-27

Создаёт все таблицы проекта Петробалт:
  route_cards, route_card_materials,
  suppliers, materials, stock_balances,
  price_history, purchase_requests, quotes
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "fb2f9df4bc0b"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── route_cards ────────────────────────────────────────────────────────
    op.create_table(
        "route_cards",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("mk_number", sa.String(100), nullable=True),
        sa.Column("product_name", sa.Text, nullable=True),
        sa.Column("quantity", sa.Numeric(12, 3), nullable=True),
        sa.Column("date_start", sa.Date, nullable=True),
        sa.Column("responsible", sa.String(255), nullable=True),
        sa.Column("status", sa.String(50), nullable=False, server_default="draft"),
        sa.Column("file_url", sa.Text, nullable=True),
        sa.Column("raw_data", sa.Text, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    # ── route_card_materials ───────────────────────────────────────────────
    op.create_table(
        "route_card_materials",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("route_card_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("position", sa.Integer, nullable=True),
        sa.Column("material_name", sa.Text, nullable=True),
        sa.Column("standard", sa.String(255), nullable=True),
        sa.Column("unit", sa.String(50), nullable=True),
        sa.Column("qty_per_unit", sa.Numeric(12, 4), nullable=True),
        sa.Column("qty_required", sa.Numeric(12, 4), nullable=True),
        sa.Column("qty_to_purchase", sa.Numeric(12, 4), nullable=True),
        sa.Column("waste_factor", sa.Numeric(6, 4), nullable=True),
        sa.ForeignKeyConstraint(
            ["route_card_id"], ["route_cards.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    # ── suppliers ──────────────────────────────────────────────────────────
    op.create_table(
        "suppliers",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("inn", sa.String(12), nullable=True),
        sa.Column("type", sa.String(50), nullable=False, server_default="unknown"),
        sa.Column("region", sa.String(100), nullable=True),
        sa.Column("contacts", sa.Text, nullable=True),
        sa.Column("verified", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("vat_registered", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("rating", sa.Numeric(3, 2), nullable=True),
        sa.Column("notes", sa.Text, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("inn", name="uq_suppliers_inn"),
    )

    # ── materials ──────────────────────────────────────────────────────────
    op.create_table(
        "materials",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("aliases", sa.Text, nullable=True),
        sa.Column("category", sa.String(100), nullable=True),
        sa.Column("unit", sa.String(50), nullable=True),
        sa.Column("waste_factor", sa.Numeric(6, 4), nullable=True),
        sa.Column("notes", sa.Text, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name", name="uq_materials_name"),
    )

    # ── stock_balances ─────────────────────────────────────────────────────
    op.create_table(
        "stock_balances",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("material_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("warehouse", sa.String(100), nullable=True),
        sa.Column(
            "quantity", sa.Numeric(14, 4), nullable=False, server_default="0"
        ),
        sa.Column("unit", sa.String(50), nullable=True),
        sa.Column(
            "reserved", sa.Numeric(14, 4), nullable=False, server_default="0"
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["material_id"], ["materials.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    # ── price_history ──────────────────────────────────────────────────────
    op.create_table(
        "price_history",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("material_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("supplier_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("price", sa.Numeric(14, 4), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False, server_default="RUB"),
        sa.Column("unit", sa.String(50), nullable=True),
        sa.Column("valid_from", sa.Date, nullable=True),
        sa.Column("valid_to", sa.Date, nullable=True),
        sa.Column("source", sa.String(100), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["material_id"], ["materials.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["supplier_id"], ["suppliers.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    # ── purchase_requests ──────────────────────────────────────────────────
    op.create_table(
        "purchase_requests",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("route_card_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("status", sa.String(50), nullable=False, server_default="new"),
        sa.Column("items", sa.Text, nullable=True),
        sa.Column("snapshot_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("notes", sa.Text, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["route_card_id"], ["route_cards.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    # ── quotes ─────────────────────────────────────────────────────────────
    op.create_table(
        "quotes",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "purchase_request_id", postgresql.UUID(as_uuid=True), nullable=True
        ),
        sa.Column("supplier_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("supplier_name", sa.String(255), nullable=True),
        sa.Column("total_price", sa.Numeric(16, 4), nullable=True),
        sa.Column("currency", sa.String(3), nullable=False, server_default="RUB"),
        sa.Column("lead_time_days", sa.Integer, nullable=True),
        sa.Column(
            "vat_included", sa.Boolean, nullable=False, server_default="true"
        ),
        sa.Column(
            "supplier_type",
            sa.String(50),
            nullable=False,
            server_default="unknown",
        ),
        sa.Column("verified", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("score", sa.Numeric(5, 4), nullable=True),
        sa.Column("file_url", sa.Text, nullable=True),
        sa.Column("notes", sa.Text, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["purchase_request_id"], ["purchase_requests.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["supplier_id"], ["suppliers.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    # ── indexes ────────────────────────────────────────────────────────────
    op.create_index("ix_route_cards_mk_number", "route_cards", ["mk_number"])
    op.create_index("ix_route_cards_status", "route_cards", ["status"])
    op.create_index("ix_suppliers_region", "suppliers", ["region"])
    op.create_index("ix_suppliers_verified", "suppliers", ["verified"])
    op.create_index(
        "ix_stock_balances_material_id", "stock_balances", ["material_id"]
    )
    op.create_index(
        "ix_price_history_material_id", "price_history", ["material_id"]
    )
    op.create_index(
        "ix_purchase_requests_route_card_id",
        "purchase_requests",
        ["route_card_id"],
    )
    op.create_index(
        "ix_purchase_requests_status", "purchase_requests", ["status"]
    )


def downgrade() -> None:
    op.drop_index("ix_purchase_requests_status", table_name="purchase_requests")
    op.drop_index(
        "ix_purchase_requests_route_card_id", table_name="purchase_requests"
    )
    op.drop_index("ix_price_history_material_id", table_name="price_history")
    op.drop_index(
        "ix_stock_balances_material_id", table_name="stock_balances"
    )
    op.drop_index("ix_suppliers_verified", table_name="suppliers")
    op.drop_index("ix_suppliers_region", table_name="suppliers")
    op.drop_index("ix_route_cards_status", table_name="route_cards")
    op.drop_index("ix_route_cards_mk_number", table_name="route_cards")

    op.drop_table("quotes")
    op.drop_table("purchase_requests")
    op.drop_table("price_history")
    op.drop_table("stock_balances")
    op.drop_table("materials")
    op.drop_table("suppliers")
    op.drop_table("route_card_materials")
    op.drop_table("route_cards")
