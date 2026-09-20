"""add missing index on applications.cycle_deadline

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-09-20 10:00:00.000000

背景：models.py 中 cycle_deadline 声明了 index=True，但初始迁移只建了
ix_applications_cycle_year，漏掉了 cycle_deadline 的索引。这个缺口此前被
启动时的 schema_sync 自动补索引掩盖，迁移链本身并不完整。
补齐后迁移链与 ORM 模型完全一致，schema 权威归一到 Alembic 一条。
"""
from collections.abc import Sequence
from typing import Union

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
