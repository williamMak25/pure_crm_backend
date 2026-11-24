from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import uuid4

from tests.conftest import ADMIN, SALES, use_company
from tests.test_auth import login

if TYPE_CHECKING:
    from litestar import Litestar
    from litestar.testing import AsyncTestClient


def new_email() -> str:
    return f"user-{uuid4().hex[:8]}@test.local"


async def add_user(client: AsyncTestClient[Litestar], email: str | None = None, **extra: str) -> dict:
    email = email or new_email()
    created = await client.post(
        "/api/settings/users", json={"name": f"Aye {email[5:13]}", "email": email, "role": "Staff", **extra}
    )
    assert created.status_code == 201, created.text
    return created.json()


async def test_members_are_per_company(client: AsyncTestClient[Litestar]) -> None:
    await login(client, ADMIN)
    created = await add_user(client, phone="09 111 222 333")
    user, password = created["user"], created["temporaryPassword"]
    assert user["role"] == "Staff" and user["companies"] == ["PURE Education"] and len(password) >= 10
    crm = next(p for p in user["permissions"] if p["module"] == "CRM & Contacts")
    assert crm["actions"]["read"] and not crm["actions"]["delete"]

    found = (await client.get("/api/settings/users", params={"search": user["email"]})).json()
    assert found["total"] == 1

    # Same email in another company: joins it with that company's role, keeps the password.
    use_company(client, "GPM")
    assert (await client.get("/api/settings/users", params={"search": user["email"]})).json()["total"] == 0
    joined = await add_user(client, user["email"], role="Manager")
    assert joined["existingAccount"] and joined["temporaryPassword"] is None
    assert joined["user"]["role"] == "Manager" and joined["user"]["companies"] == ["GPM", "PURE Education"]
    again = await client.post("/api/settings/users", json={"name": "X", "email": user["email"], "role": "Staff"})
    assert again.status_code == 400

    # Role per company: changing it at GPM leaves PURE Education alone.
    roles = {r["name"]: r for r in (await client.get("/api/settings/roles")).json()}
    assert list(roles) == ["Super Admin", "Admin", "Manager", "Accountant", "HR", "Staff"]
    updated = await client.patch(f"/api/settings/users/{user['id']}", json={"roleId": roles["Accountant"]["id"]})
    assert updated.status_code == 200 and updated.json()["role"] == "Accountant"
    use_company(client, "PURE Education")
    assert (await client.get(f"/api/settings/users/{user['id']}")).json()["role"] == "Staff"
    # A role id from another company is rejected.
    assert (
        await client.patch(f"/api/settings/users/{user['id']}", json={"roleId": roles["HR"]["id"]})
    ).status_code == 400

    # The person signs in and sees their role per company.
    await client.post("/api/auth/logout")
    await login(client, (user["email"], password))
    assert (await client.get("/api/me")).json()["role"] == "Staff"
    use_company(client, "GPM")
    assert (await client.get("/api/me")).json()["role"] == "Accountant"
    await client.post("/api/auth/logout")

    # Remove from one company: the account and the other membership stay.
    await login(client, ADMIN)
    use_company(client, "GPM")
    assert (await client.delete(f"/api/settings/users/{user['id']}/membership")).status_code == 204
    assert (await client.get(f"/api/settings/users/{user['id']}")).status_code == 404
    use_company(client, "PURE Education")
    assert (await client.get(f"/api/settings/users/{user['id']}")).json()["companies"] == ["PURE Education"]

    me = (await client.get("/api/me")).json()
    assert (await client.patch(f"/api/settings/users/{me['id']}", json={"status": "Inactive"})).status_code == 400
    assert (await client.delete(f"/api/settings/users/{me['id']}/membership")).status_code == 400

    reset = (await client.post(f"/api/settings/users/{user['id']}/reset-password")).json()
    assert reset["temporaryPassword"] != password
    assert (await client.patch(f"/api/settings/users/{user['id']}", json={"status": "Inactive"})).status_code == 200
    await client.post("/api/auth/logout")
    old = await client.post("/api/auth/login", json={"email": user["email"], "password": password})
    assert old.status_code == 401
    inactive = await client.post(
        "/api/auth/login", json={"email": user["email"], "password": reset["temporaryPassword"]}
    )
    assert inactive.status_code == 401 and "inactive" in inactive.json()["message"]


async def test_company_admin_vs_super_admin(client: AsyncTestClient[Litestar]) -> None:
    await login(client, ADMIN)
    created = await add_user(client, role="Admin")
    user, password = created["user"], created["temporaryPassword"]
    other = (await add_user(client))["user"]
    await client.post("/api/auth/logout")

    await login(client, (user["email"], password))  # Admin of PURE Education only
    assert (await client.get("/api/settings/users")).status_code == 200
    assert (await client.patch(f"/api/settings/users/{other['id']}", json={"status": "Inactive"})).status_code == 403
    assert (await client.post(f"/api/settings/users/{other['id']}/reset-password")).status_code == 403
    assert (await client.post("/api/settings/companies", json={"name": "Nope"})).status_code == 403
    use_company(client, "GPM")
    assert (await client.get("/api/settings/users")).status_code == 403


async def test_roles_and_permissions(client: AsyncTestClient[Litestar]) -> None:
    await login(client, ADMIN)
    roles = {r["name"]: r for r in (await client.get("/api/settings/roles")).json()}
    assert roles["Super Admin"]["isSystem"] and roles["Super Admin"]["users"] >= 1
    hr = roles["HR"]

    matrix = (await client.get(f"/api/settings/roles/{hr['id']}/permissions")).json()
    for row in matrix:
        if row["module"] == "Setting":
            row["actions"]["read"] = True
    saved = await client.put(f"/api/settings/roles/{hr['id']}/permissions", json=matrix)
    assert saved.status_code == 200, saved.text
    assert next(r for r in saved.json() if r["module"] == "Setting")["actions"]["read"]

    # Each company has its own matrix: GPM's HR role is unchanged.
    use_company(client, "GPM")
    gpm_hr = next(r for r in (await client.get("/api/settings/roles")).json() if r["name"] == "HR")
    gpm_matrix = (await client.get(f"/api/settings/roles/{gpm_hr['id']}/permissions")).json()
    assert not next(r for r in gpm_matrix if r["module"] == "Setting")["actions"]["read"]
    assert (await client.get(f"/api/settings/roles/{hr['id']}/permissions")).status_code == 400

    locked = next(r for r in (await client.get("/api/settings/roles")).json() if r["isSystem"])
    assert (await client.put(f"/api/settings/roles/{locked['id']}/permissions", json=matrix)).status_code == 400


async def test_company_profile_and_lifecycle(client: AsyncTestClient[Litestar]) -> None:
    await login(client, ADMIN)
    company = (await client.get("/api/settings/company")).json()
    assert company["name"] == "PURE Education" and company["currency"] == "MMK"

    saved = await client.patch(
        "/api/settings/company",
        json={
            "email": "hello@pure.test",
            "hasBranches": True,
            "branches": [
                {"id": "new-1", "name": "Yangon HQ", "address": "Pyay Road", "phone": "09 1"},
                {"id": "new-2", "name": "Mandalay"},
            ],
        },
    )
    assert saved.status_code == 200, saved.text
    branches = saved.json()["branches"]
    assert [b["name"] for b in branches] == ["Yangon HQ", "Mandalay"]
    kept = await client.patch("/api/settings/company", json={"branches": [{"id": branches[0]["id"], "name": "Yangon"}]})
    assert [(b["id"], b["name"]) for b in kept.json()["branches"]] == [(branches[0]["id"], "Yangon")]

    # GPM has its own details and branches.
    use_company(client, "GPM")
    gpm = (await client.get("/api/settings/company")).json()
    assert gpm["name"] == "GPM" and gpm["branches"] == [] and gpm["email"] != "hello@pure.test"
    assert (await client.patch("/api/settings/company", json={"name": "pure education"})).status_code == 400

    # Add a company: it gets roles, a pipeline, and the super admin as a member.
    created = await client.post("/api/settings/companies", json={"name": "Test Company"})
    assert created.status_code == 201, created.text
    new = created.json()
    assert new["slug"] == "test-company" and new["members"] >= 1
    assert "Test Company" in {b["name"] for b in (await client.get("/api/businesses")).json()}
    use_company(client, "test-company")
    assert [s["name"] for s in (await client.get("/api/crm/pipeline")).json()] == [
        "New",
        "Contacted",
        "Qualified",
        "Won",
    ]
    assert len((await client.get("/api/settings/roles")).json()) == 6
    renamed = await client.patch("/api/settings/company", json={"name": "Test Company Renamed"})
    assert renamed.json()["name"] == "Test Company Renamed"

    # Deleting is refused while it has records.
    contact = (await client.post("/api/crm/contacts", json={"name": "Someone"})).json()
    blocked = await client.delete(f"/api/settings/companies/{new['id']}")
    assert blocked.status_code == 409 and "still has 1 contact" in blocked.json()["message"]
    await client.delete(f"/api/crm/contacts/{contact['id']}")
    assert (await client.delete(f"/api/settings/companies/{new['id']}")).status_code == 204
    use_company(client, "PURE Education")
    assert "Test Company Renamed" not in {b["name"] for b in (await client.get("/api/businesses")).json()}


async def test_security_and_own_password(client: AsyncTestClient[Litestar]) -> None:
    await login(client, ADMIN)
    updated = await client.put(
        "/api/settings/security",
        json={"twoFactor": True, "loginAlerts": False, "sessionTimeout": "1 hour", "passwordExpiry": "90 days"},
    )
    assert updated.json()["sessionTimeout"] == "1 hour"
    use_company(client, "GPM")
    assert (await client.get("/api/settings/security")).json()["sessionTimeout"] == "30 minutes"
    invalid = await client.put(
        "/api/settings/security",
        json={"twoFactor": True, "loginAlerts": False, "sessionTimeout": "2 days", "passwordExpiry": "Never"},
    )
    assert invalid.status_code == 400

    use_company(client, "PURE Education")
    created = await add_user(client)
    email, password = created["user"]["email"], created["temporaryPassword"]
    await client.post("/api/auth/logout")
    await login(client, (email, password))
    assert (
        await client.post("/api/me/password", json={"currentPassword": "nope", "newPassword": "NewPass123!"})
    ).status_code == 400
    changed = await client.post("/api/me/password", json={"currentPassword": password, "newPassword": "NewPass123!"})
    assert changed.status_code == 204
    assert (await client.get("/api/settings/users")).status_code == 403  # Staff has no Settings permission
    await client.post("/api/auth/logout")
    assert (await client.post("/api/auth/login", json={"email": email, "password": "NewPass123!"})).status_code == 200

    await client.post("/api/auth/logout")
    await login(client, SALES)
    assert (await client.get("/api/settings/company")).status_code == 403
