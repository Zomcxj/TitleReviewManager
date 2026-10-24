"""add missing index on applications.cycle_deadline

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-09-20 10:00:00.000000

Background: cycle_deadline is declared with index=True in models.py, but the
initial migration only created ix_applications_cycle_year and missed the index
on cycle_deadline. This gap was previously masked by schema_sync automatically
creating the missing index at startup, leaving the migration chain itself
incomplete. With this index added, the migration chain fully matches the ORM
models, and Alembic becomes the single source of truth for the schema.
"""
from collections.abc import Sequence

from alembic import op


revision: str = "b2c3d4e5f6a7"
down_revision: str | Sequence[str] | None = "a1b2c3d4e5f6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index(
        op.f("ix_applications_cycle_deadline"),
        "applications",
        ["cycle_deadline"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_applications_cycle_deadline"), table_name="applications")
