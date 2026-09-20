"""add review sla deadline on applications

Revision ID: a1b2c3d4e5f6
Revises: 7745fb77bcce
Create Date: 2026-09-19 12:00:00.000000

"""
from collections.abc import Sequence
from typing import Union

from alembic import op
import sqlalchemy as sa


revision: str = "a1b2c3d4e5f6"
down_revision: str | Sequence[str] | None = "7745fb77bcce"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("applications", schema=None) as batch_op:
        batch_op.add_column(sa.Column(
            "review_sla_deadline",
            sa.DateTime(),
            nullable=True,
            comment="内部审核 SLA 截止时间（进入完成资料时写入，离开待审状态时清空）",
        ))
        batch_op.create_index(
            batch_op.f("ix_applications_review_sla_deadline"),
            ["review_sla_deadline"],
            unique=False,
        )


def downgrade() -> None:
    with op.batch_alter_table("applications", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_applications_review_sla_deadline"))
        batch_op.drop_column("review_sla_deadline")
