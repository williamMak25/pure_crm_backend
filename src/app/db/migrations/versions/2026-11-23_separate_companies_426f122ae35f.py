"""separate companies

Revision ID: 426f122ae35f
Revises: 5bf805563665
Create Date: 2026-11-23 02:01:34.425193

"""

import uuid
import warnings
from typing import TYPE_CHECKING

import sqlalchemy as sa
from alembic import op
from advanced_alchemy.types import (
    EncryptedString,
    EncryptedText,
    GUID,
    ORA_JSONB,
    DateTimeUTC,
    StoredObject,
    PasswordHash,
)
from sqlalchemy import Text  # pyright: ignore  # noqa: F401

if TYPE_CHECKING:
    from collections.abc import Sequence  # pyright: ignore

__all__ = ("downgrade", "upgrade", "schema_upgrades", "schema_downgrades", "data_upgrades", "data_downgrades")

sa.GUID = GUID  # pyright: ignore
sa.DateTimeUTC = DateTimeUTC  # pyright: ignore
sa.ORA_JSONB = ORA_JSONB  # pyright: ignore
sa.EncryptedString = EncryptedString  # pyright: ignore
sa.EncryptedText = EncryptedText  # pyright: ignore
sa.StoredObject = StoredObject  # pyright: ignore
sa.PasswordHash = PasswordHash  # pyright: ignore

# revision identifiers, used by Alembic.
revision = "426f122ae35f"
down_revision = "5bf805563665"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # One transaction (not the template's autocommit block): if any step fails, nothing is applied.
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", category=UserWarning)
        schema_upgrades()
        data_upgrades()


def downgrade() -> None:
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", category=UserWarning)
        with op.get_context().autocommit_block():
            data_downgrades()
            schema_downgrades()


def schema_upgrades() -> None:
    """Each switcher entry (business row) becomes a separate company.

    1. Company details move from the single `company` row onto every business.
    2. Security settings and branches belong to a business.
    3. Every business gets its own copy of each role (with permissions); each membership gets the copy of
       the person's old global role, and super admins become Super Admin members of every company.
    Nobody's access changes. This migration is one-way: restore the backup to go back.
    """
    conn = op.get_bind()

    # 1. company details -> each business
    with op.batch_alter_table("business", schema=None) as batch_op:
        batch_op.add_column(sa.Column("email", sa.String(length=320), nullable=True))
        batch_op.add_column(sa.Column("phone", sa.String(length=50), nullable=True))
        batch_op.add_column(sa.Column("address", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("currency", sa.String(length=3), server_default="MMK", nullable=False))
        batch_op.add_column(sa.Column("timezone", sa.String(length=64), server_default="Asia/Yangon", nullable=False))
        batch_op.add_column(sa.Column("has_branches", sa.Boolean(), server_default="false", nullable=False))
    conn.execute(
        sa.text(
            "UPDATE business b SET email = c.email, phone = c.phone, address = c.address, currency = c.currency, "
            "timezone = c.timezone, has_branches = c.has_branches FROM company c WHERE c.id = b.company_id"
        )
    )

    # 2a. security settings: one row per business, copied from its group's row
    with op.batch_alter_table("security_settings", schema=None) as batch_op:
        batch_op.add_column(sa.Column("business_id", sa.GUID(length=16), nullable=True))
        # one row per business from now on, so the old one-per-group rule goes first
        batch_op.drop_constraint(batch_op.f("uq_security_settings_company_id"), type_="unique")
    conn.execute(
        sa.text(
            "INSERT INTO security_settings (id, business_id, company_id, two_factor, login_alerts, "
            "session_timeout_minutes, password_expiry_days, created_at, updated_at) "
            "SELECT gen_random_uuid(), b.id, s.company_id, s.two_factor, s.login_alerts, s.session_timeout_minutes, "
            "s.password_expiry_days, now(), now() FROM business b JOIN security_settings s ON s.company_id = b.company_id "
            "WHERE s.business_id IS NULL"
        )
    )
    conn.execute(sa.text("DELETE FROM security_settings WHERE business_id IS NULL"))
    with op.batch_alter_table("security_settings", schema=None) as batch_op:
        batch_op.drop_constraint(batch_op.f("fk_security_settings_company_id_company"), type_="foreignkey")
        batch_op.drop_column("company_id")
        batch_op.alter_column("business_id", nullable=False)
        batch_op.create_unique_constraint(batch_op.f("uq_security_settings_business_id"), ["business_id"])
        batch_op.create_foreign_key(
            batch_op.f("fk_security_settings_business_id_business"),
            "business",
            ["business_id"],
            ["id"],
            ondelete="CASCADE",
        )

    # 2b. branches already have business_id; drop the group link
    with op.batch_alter_table("branch", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_branch_company_id"))
        batch_op.drop_constraint(batch_op.f("fk_branch_company_id_company"), type_="foreignkey")
        batch_op.drop_column("company_id")

    # 3. roles per business, memberships carry the role
    with op.batch_alter_table("role", schema=None) as batch_op:
        batch_op.add_column(sa.Column("business_id", sa.GUID(length=16), nullable=True))
        batch_op.drop_constraint(batch_op.f("uq_role_name"), type_="unique")
    with op.batch_alter_table("user_business", schema=None) as batch_op:
        batch_op.add_column(sa.Column("role_id", sa.GUID(length=16), nullable=True))

    old_roles = conn.execute(
        sa.text("SELECT id, name, description, is_system FROM role WHERE business_id IS NULL")
    ).all()
    businesses = [row.id for row in conn.execute(sa.text("SELECT id FROM business")).all()]
    for business_id in businesses:
        for old in old_roles:
            new_id = uuid.uuid4()
            conn.execute(
                sa.text(
                    "INSERT INTO role (id, business_id, name, description, is_system, created_at, updated_at) "
                    "VALUES (:id, :b, :name, :d, :sys, now(), now())"
                ),
                {"id": new_id, "b": business_id, "name": old.name, "d": old.description, "sys": old.is_system},
            )
            conn.execute(
                sa.text(
                    "INSERT INTO role_permission (id, role_id, module, action, created_at, updated_at) "
                    "SELECT gen_random_uuid(), :new, module, action, now(), now() FROM role_permission WHERE role_id = :old"
                ),
                {"new": new_id, "old": old.id},
            )
            # Members of this business who had the old role get its copy here.
            conn.execute(
                sa.text(
                    "UPDATE user_business ub SET role_id = :new FROM user_account u "
                    "WHERE u.id = ub.user_id AND ub.business_id = :b AND u.role_id = :old"
                ),
                {"new": new_id, "b": business_id, "old": old.id},
            )
        # Super admins become Super Admin members of every company.
        conn.execute(
            sa.text(
                "INSERT INTO user_business (user_id, business_id, role_id) "
                "SELECT u.id, :b, (SELECT r.id FROM role r WHERE r.business_id = :b AND r.is_system LIMIT 1) "
                "FROM user_account u WHERE u.is_superuser "
                "AND NOT EXISTS (SELECT 1 FROM user_business x WHERE x.user_id = u.id AND x.business_id = :b)"
            ),
            {"b": business_id},
        )
    with op.batch_alter_table("user_account", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_user_account_role_id"))
        batch_op.drop_constraint(batch_op.f("fk_user_account_role_id_role"), type_="foreignkey")
        batch_op.drop_column("role_id")
    conn.execute(sa.text("DELETE FROM role WHERE business_id IS NULL"))
    with op.batch_alter_table("role", schema=None) as batch_op:
        batch_op.alter_column("business_id", nullable=False)
        batch_op.create_index(batch_op.f("ix_role_business_id"), ["business_id"], unique=False)
        batch_op.create_unique_constraint("uq_role_business_name", ["business_id", "name"])
        batch_op.create_foreign_key(
            batch_op.f("fk_role_business_id_business"), "business", ["business_id"], ["id"], ondelete="CASCADE"
        )
    with op.batch_alter_table("user_business", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_user_business_role_id"), ["role_id"], unique=False)
        batch_op.create_foreign_key(
            batch_op.f("fk_user_business_role_id_role"), "role", ["role_id"], ["id"], ondelete="SET NULL"
        )

    # 4. the group row keeps only its name
    with op.batch_alter_table("company", schema=None) as batch_op:
        for column in ("currency", "timezone", "has_branches", "address", "email", "phone"):
            batch_op.drop_column(column)


def schema_downgrades() -> None:
    """One-way: per-company roles and settings can't be merged back automatically."""
    msg = "Downgrading 'separate companies' is not supported. Restore the database backup taken before upgrading."
    raise NotImplementedError(msg)


def data_upgrades() -> None:
    """Add any optional data upgrade migrations here!"""


def data_downgrades() -> None:
    """Add any optional data downgrade migrations here!"""
