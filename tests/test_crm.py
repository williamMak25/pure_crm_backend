from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import uuid4

from tests.conftest import ADMIN, SALES
from tests.test_auth import login

if TYPE_CHECKING:
    from litestar import Litestar
    from litestar.testing import AsyncTestClient


def unique(prefix: str) -> str:
    return f"{prefix} {uuid4().hex[:8]}"


async def test_contact_crud(client: AsyncTestClient[Litestar]) -> None:
    await login(client, ADMIN)
    name = unique("Aung Myint")
    created = await client.post(
        "/api/crm/contacts",
        json={
            "name": name,
            "company": "ABC Education",
            "email": "aung@example.com",
            "business": "PURE Education",
            "followUpDate": "2026-10-15",
            "status": "Active",
        },
    )
    assert created.status_code == 201, created.text
    contact = created.json()
    assert contact["business"] == "PURE Education"
    assert contact["owner"] == "Test Admin"  # defaults to the signed-in user
    assert contact["followUpDate"] == "2026-10-15"

    listed = (await client.get("/api/crm/contacts", params={"search": name.split()[-1]})).json()
    assert listed["total"] == 1
    assert listed["items"][0]["id"] == contact["id"]
    assert set(listed) == {"items", "total", "page", "pageSize"}

    elsewhere = await client.get("/api/crm/contacts", params={"search": name.split()[-1], "business": "GPM"})
    assert elsewhere.json()["total"] == 0

    updated = await client.patch(
        f"/api/crm/contacts/{contact['id']}", json={"status": "Archived", "business": "gpm", "owner": "Test Admin"}
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["status"] == "Archived"
    assert updated.json()["business"] == "GPM"

    assert (await client.delete(f"/api/crm/contacts/{contact['id']}")).status_code == 204
    assert (await client.get(f"/api/crm/contacts/{contact['id']}")).status_code == 404


async def test_contact_validation(client: AsyncTestClient[Litestar]) -> None:
    await login(client, ADMIN)
    bad_email = await client.post("/api/crm/contacts", json={"name": "X", "email": "nope", "business": "GPM"})
    assert bad_email.status_code == 400
    assert "message" in bad_email.json()

    unknown_business = await client.post("/api/crm/contacts", json={"name": "X", "business": "Nowhere"})
    assert unknown_business.status_code == 400
    assert "Nowhere" in unknown_business.json()["message"]

    unknown_owner = await client.post("/api/crm/contacts", json={"name": "X", "business": "GPM", "owner": "Nobody"})
    assert unknown_owner.status_code == 400

    bad_status = await client.get("/api/crm/contacts", params={"status": "Sleeping"})
    assert bad_status.status_code == 400


async def test_sales_user_is_limited_to_their_business(client: AsyncTestClient[Litestar]) -> None:
    await login(client, ADMIN)
    gpm = (await client.post("/api/crm/contacts", json={"name": unique("GPM lead"), "business": "GPM"})).json()
    await client.post("/api/auth/logout")

    await login(client, SALES)
    assert (await client.post("/api/crm/contacts", json={"name": "X", "business": "GPM"})).status_code == 403
    assert (await client.get(f"/api/crm/contacts/{gpm['id']}")).status_code == 404
    assert (await client.get("/api/crm/contacts", params={"business": "GPM"})).status_code == 403

    mine = await client.post("/api/crm/contacts", json={"name": unique("Pure lead"), "business": "PURE Education"})
    assert mine.status_code == 201
    assert mine.json()["owner"] == "Test Sales"

    businesses = {row["business"] for row in (await client.get("/api/crm/contacts")).json()["items"]}
    assert businesses == {"PURE Education"}

    # The Sales role can create and update in CRM but not delete.
    assert (await client.delete(f"/api/crm/contacts/{mine.json()['id']}")).status_code == 403


async def test_universities_and_consultants(client: AsyncTestClient[Litestar]) -> None:
    await login(client, ADMIN)
    uni = await client.post(
        "/api/crm/universities",
        json={"name": unique("Pacific Business"), "country": "Australia", "business": "PURE Education"},
    )
    assert uni.status_code == 201, uni.text
    assert uni.json()["status"] == "Active"
    assert (await client.patch(f"/api/crm/universities/{uni.json()['id']}", json={"status": "Pending"})).json()[
        "status"
    ] == "Pending"

    consultant = await client.post(
        "/api/crm/consultants",
        json={"name": unique("Min Aye"), "company": "XYZ Group", "country": "Japan", "business": "Anime House"},
    )
    assert consultant.status_code == 201, consultant.text
    assert consultant.json()["company"] == "XYZ Group"
    listed = (await client.get("/api/crm/consultants", params={"status": "Active", "business": "Anime House"})).json()
    assert consultant.json()["id"] in {row["id"] for row in listed["items"]}


async def test_pipeline(client: AsyncTestClient[Litestar]) -> None:
    await login(client, ADMIN)
    stages = (await client.get("/api/crm/pipeline", params={"business": "Anime House"})).json()
    assert [s["name"] for s in stages][:4] == ["New", "Contacted", "Qualified", "Won"]
    new, contacted = stages[0], stages[1]

    deal = await client.post(
        f"/api/crm/pipeline/{new['id']}/deals",
        json={"name": unique("Aung Myint"), "company": "ABC Education", "amount": 40000, "tags": ["Tiktok"]},
    )
    assert deal.status_code == 201, deal.text
    card = deal.json()
    assert card["company"] == "ABC Education"
    assert card["owner"]["name"] == "Test Admin"
    contact = (await client.get(f"/api/crm/contacts/{card['contactId']}")).json()
    assert contact["status"] == "Lead"

    moved = await client.patch(f"/api/crm/deals/{card['id']}", json={"stageId": contacted["id"], "rating": 2})
    assert moved.status_code == 200, moved.text
    assert moved.json()["stageId"] == contacted["id"]

    second = (await client.post(f"/api/crm/pipeline/{contacted['id']}/deals", json={"name": unique("Min Thu")})).json()
    dropped = await client.patch(f"/api/crm/deals/{second['id']}", json={"position": 0})
    assert dropped.status_code == 200, dropped.text
    stage = next(
        s
        for s in (await client.get("/api/crm/pipeline", params={"business": "Anime House"})).json()
        if s["id"] == contacted["id"]
    )
    assert stage["deals"][0]["id"] == second["id"]
    assert (await client.delete(f"/api/crm/deals/{second['id']}")).status_code == 204

    board = {s["id"]: s for s in (await client.get("/api/crm/pipeline", params={"business": "anime-house"})).json()}
    assert board[contacted["id"]]["total"] >= 40000
    assert sum(s["progress"] for s in board.values()) == 1

    added = await client.post("/api/crm/pipeline", json={"name": "Proposal", "business": "Anime House"})
    assert added.status_code == 201
    assert added.json()["position"] == len(stages)

    blocked = await client.delete(f"/api/crm/pipeline/{contacted['id']}")
    assert blocked.status_code == 409
    assert (await client.delete(f"/api/crm/deals/{card['id']}")).status_code == 204
    assert (await client.delete(f"/api/crm/pipeline/{added.json()['id']}")).status_code == 204

    other = (await client.get("/api/crm/pipeline", params={"business": "GPM"})).json()
    cross = await client.patch(f"/api/crm/deals/{uuid4()}", json={"stageId": other[0]["id"]})
    assert cross.status_code == 404


async def test_deal_detail_timeline_and_activities(client: AsyncTestClient[Litestar]) -> None:
    await login(client, ADMIN)
    stages = (await client.get("/api/crm/pipeline", params={"business": "GPM"})).json()
    new, contacted = stages[0], stages[1]
    uni = (await client.post("/api/crm/universities", json={"name": unique("KMD College"), "business": "GPM"})).json()
    consultant = (await client.post("/api/crm/consultants", json={"name": unique("Min Aye"), "business": "GPM"})).json()
    people = (await client.get("/api/crm/people", params={"business": "GPM"})).json()
    assert "Test Admin" in {p["name"] for p in people}

    card = (
        await client.post(
            f"/api/crm/pipeline/{new['id']}/deals",
            json={"name": unique("Aung Myint"), "email": "aung@example.com", "universityIds": [uni["id"]]},
        )
    ).json()
    detail = (await client.get(f"/api/crm/deals/{card['id']}")).json()
    assert detail["email"] == "aung@example.com"
    assert detail["stageName"] == "New"
    assert [u["name"] for u in detail["universities"]] == [uni["name"]]

    edited = await client.patch(
        f"/api/crm/deals/{card['id']}",
        json={
            "contact": "Aung Myint Updated",
            "phone": "+959 954382221",
            "socialMediaLink": "https://www.facebook.com/aung",
            "consultantId": consultant["id"],
            "universityIds": [],
            "tags": ["Airline Business", "SPU"],
            "stageId": contacted["id"],
        },
    )
    assert edited.status_code == 200, edited.text
    body = edited.json()
    assert body["name"] == "Aung Myint Updated"
    assert body["phone"] == "+959 954382221"
    assert body["consultant"]["id"] == consultant["id"]
    assert body["universities"] == []
    assert body["stageName"] == "Contacted"
    contact = (await client.get(f"/api/crm/contacts/{card['contactId']}")).json()
    assert contact["name"] == "Aung Myint Updated"

    sent = await client.post(
        f"/api/crm/deals/{card['id']}/messages", json={"subject": "Greeting", "body": "Hello, how are you?"}
    )
    assert sent.status_code == 201, sent.text
    assert sent.json()["recipient"] == "aung@example.com"
    assert sent.json()["stageName"] == "Contacted"
    note = await client.post(f"/api/crm/deals/{card['id']}/messages", json={"kind": "note", "body": "Called back"})
    assert note.status_code == 201

    notes = (await client.get(f"/api/crm/deals/{card['id']}/messages", params={"kind": "note"})).json()
    assert notes[0]["body"] == "Called back"
    assert any("Stage changed from New to Contacted" in n["body"] for n in notes)
    found = (await client.get(f"/api/crm/deals/{card['id']}/messages", params={"search": "greet"})).json()
    assert [m["subject"] for m in found] == ["Greeting"]

    activity = await client.post(
        f"/api/crm/deals/{card['id']}/activities", json={"kind": "Call", "dueDate": "2026-10-21"}
    )
    assert activity.status_code == 201, activity.text
    assert activity.json()["summary"] == "Call"
    assert activity.json()["assignedTo"]["name"] == "Test Admin"
    done = await client.patch(f"/api/crm/deal-activities/{activity.json()['id']}", json={"done": True})
    assert done.json()["done"] is True
    assert len((await client.get(f"/api/crm/deals/{card['id']}/activities")).json()) == 1
    assert (await client.delete(f"/api/crm/deal-activities/{activity.json()['id']}")).status_code == 204

    other_uni = (
        await client.post("/api/crm/universities", json={"name": unique("MCU"), "business": "Anime House"})
    ).json()
    cross = await client.patch(f"/api/crm/deals/{card['id']}", json={"universityIds": [other_uni["id"]]})
    assert cross.status_code == 400
