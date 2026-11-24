"""figma role names

Revision ID: d2ece0c856c1
Revises: 8add02d31743
Create Date: 2026-11-23 01:35:03.142156

"""

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
revision = "d2ece0c856c1"
down_revision = "8add02d31743"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", category=UserWarning)
        with op.get_context().autocommit_block():
            schema_upgrades()
            data_upgrades()


def downgrade() -> None:
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", category=UserWarning)
        with op.get_context().autocommit_block():
            data_downgrades()
            schema_downgrades()


def schema_upgrades() -> None:
    """schema upgrade migrations go here."""
    pass


def schema_downgrades() -> None:
    """schema downgrade migrations go here."""
    pass


# Rename the seeded roles to the Figma "Roles & Permissions" set. Nobody's access changes:
# Admin -> Super Admin (system role), Finance -> Accountant, Sales -> Staff (same permissions),
# Viewer is dropped if unused, and a new "Admin" role is added.
RENAMES = [
    ("Admin", "Super Admin", "Full access to every module and setting."),
    ("Finance", "Accountant", "Invoices, payments and finance."),
    ("Sales", "Staff", "Day-to-day CRM, sales and project work."),
]
DESCRIPTIONS = {
    "Manager": "Manage teams and approve requests.",
    "HR": "Employees, attendance, leave and payroll.",
}
ADMIN_DESCRIPTION = "Manages every module, users and company details."
ALL_ACTIONS = ("create", "read", "update", "delete", "approve")
ADMIN_MATRIX = {
    **{module: ALL_ACTIONS for module in ("overview", "crm", "projects", "sales", "invoices", "finance", "hr")},
    "settings": ("create", "read", "update"),
}


def data_upgrades() -> None:
    """Add any optional data upgrade migrations here!"""
    import uuid

    conn = op.get_bind()
    if not conn.scalar(sa.text("SELECT count(*) FROM role")):
        return  # fresh database: `app seed` creates the new roles
    for old, new, description in RENAMES:
        conn.execute(
            sa.text("UPDATE role SET name = :new, description = :d, updated_at = now() WHERE name = :old"),
            {"old": old, "new": new, "d": description},
        )
    for name, description in DESCRIPTIONS.items():
        conn.execute(sa.text("UPDATE role SET description = :d WHERE name = :n"), {"n": name, "d": description})
    conn.execute(
        sa.text(
            "DELETE FROM role WHERE name = 'Viewer' AND NOT EXISTS (SELECT 1 FROM user_account u WHERE u.role_id = role.id)"
        )
    )
    if conn.scalar(sa.text("SELECT 1 FROM role WHERE name = 'Admin'")):
        return
    role_id = uuid.uuid4()
    conn.execute(
        sa.text(
            "INSERT INTO role (id, name, description, is_system, created_at, updated_at) "
            "VALUES (:id, 'Admin', :d, false, now(), now())"
        ),
        {"id": role_id, "d": ADMIN_DESCRIPTION},
    )
    for module, actions in ADMIN_MATRIX.items():
        for action in actions:
            conn.execute(
                sa.text(
                    "INSERT INTO role_permission (id, role_id, module, action, created_at, updated_at) "
                    "VALUES (:id, :role, CAST(:module AS app_module), CAST(:action AS permission_action), now(), now())"
                ),
                {"id": uuid.uuid4(), "role": role_id, "module": module, "action": action},
            )


def data_downgrades() -> None:
    """Add any optional data downgrade migrations here!"""
    conn = op.get_bind()
    # Users on the new Admin role lose it (role_id is ON DELETE SET NULL); Viewer is not recreated.
    conn.execute(sa.text("DELETE FROM role WHERE name = 'Admin' AND NOT is_system"))
    for old, new, _ in RENAMES:
        conn.execute(sa.text("UPDATE role SET name = :old WHERE name = :new"), {"old": old, "new": new})
