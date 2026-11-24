from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import uuid4

from tests.conftest import ADMIN, SALES, use_company
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
            "followUpDate": "2026-10-15",
            "status": "Active",
        },
    )
    assert created.status_code == 201, created.text
    contact = created.json()
    assert contact["business"] == "PURE Education"  # the selected company
    assert contact["owner"] == "Test Admin"  # defaults to the signed-in user
    assert contact["followUpDate"] == "2026-10-15"

    listed = (await client.get("/api/crm/contacts", params={"search": name.split()[-1]})).json()
    assert listed["total"] == 1
    assert listed["items"][0]["id"] == contact["id"]
    assert set(listed) == {"items", "total", "page", "pageSize"}

    updated = await client.patch(
        f"/api/crm/contacts/{contact['id']}", json={"status": "Archived", "owner": "Test Admin"}
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["status"] == "Archived"

    # Another company doesn't see it at all.
    use_company(client, "GPM")
    assert (await client.get("/api/crm/contacts", params={"search": name.split()[-1]})).json()["total"] == 0
    assert (await client.get(f"/api/crm/contacts/{contact['id']}")).status_code == 404
    assert (await client.delete(f"/api/crm/contacts/{contact['id']}")).status_code == 404

    use_company(client, "PURE Education")
    assert (await client.delete(f"/api/crm/contacts/{contact['id']}")).status_code == 204
    assert (await client.get(f"/api/crm/contacts/{contact['id']}")).status_code == 404


async def test_contact_validation(client: AsyncTestClient[Litestar]) -> None:
    await login(client, ADMIN)
    bad_email = await client.post("/api/crm/contacts", json={"name": "X", "email": "nope"})
    assert bad_email.status_code == 400
    assert "message" in bad_email.json()

    unknown_owner = await client.post("/api/crm/contacts", json={"name": "X", "owner": "Nobody"})
    assert unknown_owner.status_code == 400

    bad_status = await client.get("/api/crm/contacts", params={"status": "Sleeping"})
    assert bad_status.status_code == 400


async def test_member_only_sees_their_company(client: AsyncTestClient[Litestar]) -> None:
    await login(client, ADMIN)
    use_company(client, "GPM")
    gpm = (await client.post("/api/crm/contacts", json={"name": unique("GPM lead")})).json()
    await client.post("/api/auth/logout")

    await login(client, SALES)  # Staff at PURE Education only
    use_company(client, "GPM")
    assert (await client.get("/api/crm/contacts")).status_code == 403
    assert (await client.post("/api/crm/contacts", json={"name": "X"})).status_code == 403

    use_company(client, "PURE Education")
    assert (await client.get(f"/api/crm/contacts/{gpm['id']}")).status_code == 404
    mine = await client.post("/api/crm/contacts", json={"name": unique("Pure lead")})
    assert mine.status_code == 201
    assert mine.json()["owner"] == "Test Sales"
    companies = {row["business"] for row in (await client.get("/api/crm/contacts")).json()["items"]}
    assert companies == {"PURE Education"}

    # The Staff role can create and update in CRM but not delete.
    assert (await client.delete(f"/api/crm/contacts/{mine.json()['id']}")).status_code == 403


async def test_universities_and_consultants(client: AsyncTestClient[Litestar]) -> None:
    await login(client, ADMIN)
    uni = await client.post("/api/crm/universities", json={"name": unique("Pacific Business"), "country": "Australia"})
    assert uni.status_code == 201, uni.text
    assert uni.json()["status"] == "Active"
    assert (await client.patch(f"/api/crm/universities/{uni.json()['id']}", json={"status": "Pending"})).json()[
        "status"
    ] == "Pending"

    use_company(client, "Anime House")
    consultant = await client.post(
        "/api/crm/consultants", json={"name": unique("Min Aye"), "company": "XYZ Group", "country": "Japan"}
    )
    assert consultant.status_code == 201, consultant.text
    assert consultant.json()["company"] == "XYZ Group" and consultant.json()["business"] == "Anime House"
    listed = (await client.get("/api/crm/consultants", params={"status": "Active"})).json()
    assert consultant.json()["id"] in {row["id"] for row in listed["items"]}


async def test_pipeline(client: AsyncTestClient[Litestar]) -> None:
    await login(client, ADMIN)
    use_company(client, "anime-house")
    stages = (await client.get("/api/crm/pipeline")).json()
    assert [s["name"] for s in stages][:4] == ["New", "Contacted", "Qualified", "Won"]
    new, contacted = stages[0], stages[1]

    deal = await client.post(
        f"/api/crm/pipeline/{new['id']}/deals",
        json={"name": unique("Aung Myint"), "company": "ABC Education", "amount": 40000, "tags": ["Tiktok"]},
    )
    assert deal.status_code == 201, deal.text
    card = deal.json()
    assert card["company"] == "ABC Education"
    assert card["owner"]["name"] == "Test Admin" and card["owner"]["role"] == "Super Admin"
    lead = (await client.get(f"/api/crm/leads/{card['contactId']}")).json()
    assert lead["status"] == "In Pipeline" and lead["dealId"] == card["id"]
    assert (await client.get(f"/api/crm/contacts/{card['contactId']}")).status_code == 404  # not a student

    moved = await client.patch(f"/api/crm/deals/{card['id']}", json={"stageId": contacted["id"], "rating": 2})
    assert moved.status_code == 200, moved.text
    assert moved.json()["stageId"] == contacted["id"]

    second = (await client.post(f"/api/crm/pipeline/{contacted['id']}/deals", json={"name": unique("Min Thu")})).json()
    dropped = await client.patch(f"/api/crm/deals/{second['id']}", json={"position": 0})
    assert dropped.status_code == 200, dropped.text
    stage = next(s for s in (await client.get("/api/crm/pipeline")).json() if s["id"] == contacted["id"])
    assert stage["deals"][0]["id"] == second["id"]
    assert (await client.delete(f"/api/crm/deals/{second['id']}")).status_code == 204

    board = {s["id"]: s for s in (await client.get("/api/crm/pipeline")).json()}
    assert board[contacted["id"]]["total"] >= 40000
    assert sum(s["progress"] for s in board.values()) == 1

    added = await client.post("/api/crm/pipeline", json={"name": "Proposal"})
    assert added.status_code == 201
    assert added.json()["position"] == len(stages)

    blocked = await client.delete(f"/api/crm/pipeline/{contacted['id']}")
    assert blocked.status_code == 409
    assert (await client.delete(f"/api/crm/deals/{card['id']}")).status_code == 204
    assert (await client.delete(f"/api/crm/pipeline/{added.json()['id']}")).status_code == 204

    # A stage of another company can't receive this company's deal.
    use_company(client, "GPM")
    other = (await client.get("/api/crm/pipeline")).json()
    use_company(client, "Anime House")
    third = (await client.post(f"/api/crm/pipeline/{new['id']}/deals", json={"name": unique("Cross")})).json()
    assert (await client.patch(f"/api/crm/deals/{third['id']}", json={"stageId": other[0]["id"]})).status_code == 404
    await client.delete(f"/api/crm/deals/{third['id']}")


async def test_deal_detail_timeline_and_activities(client: AsyncTestClient[Litestar]) -> None:
    await login(client, ADMIN)
    use_company(client, "GPM")
    stages = (await client.get("/api/crm/pipeline")).json()
    new, contacted = stages[0], stages[1]
    uni = (await client.post("/api/crm/universities", json={"name": unique("KMD College")})).json()
    consultant = (await client.post("/api/crm/consultants", json={"name": unique("Min Aye")})).json()
    people = (await client.get("/api/crm/people")).json()
    assert "Test Admin" in {p["name"] for p in people}

    card = (
        await client.post(
            f"/api/crm/pipeline/{new['id']}/deals",
            json={"name": unique("Aung Myint"), "email": "aung@example.com", "universityId": uni["id"]},
        )
    ).json()
    detail = (await client.get(f"/api/crm/deals/{card['id']}")).json()
    assert detail["email"] == "aung@example.com"
    assert detail["stageName"] == "New"
    assert detail["university"] == {"id": uni["id"], "name": uni["name"]}

    # One university per lead: picking another replaces it.
    second = (await client.post("/api/crm/universities", json={"name": unique("SPU")})).json()
    swapped = (await client.patch(f"/api/crm/deals/{card['id']}", json={"universityId": second["id"]})).json()
    assert swapped["university"]["id"] == second["id"]

    edited = await client.patch(
        f"/api/crm/deals/{card['id']}",
        json={
            "contact": "Aung Myint Updated",
            "phone": "+959 954382221",
            "socialMediaLink": "https://www.facebook.com/aung",
            "consultantId": consultant["id"],
            "universityId": None,
            "tags": ["Airline Business", "SPU"],
            "stageId": contacted["id"],
        },
    )
    assert edited.status_code == 200, edited.text
    body = edited.json()
    assert body["name"] == "Aung Myint Updated"
    assert body["phone"] == "+959 954382221"
    assert body["consultant"]["id"] == consultant["id"]
    assert body["university"] is None
    assert body["stageName"] == "Contacted"
    contact = (await client.get(f"/api/crm/leads/{card['contactId']}")).json()
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

    use_company(client, "Anime House")
    other_uni = (await client.post("/api/crm/universities", json={"name": unique("MCU")})).json()
    use_company(client, "GPM")
    cross = await client.patch(f"/api/crm/deals/{card['id']}", json={"universityId": other_uni["id"]})
    assert cross.status_code == 400


async def test_leads_move_into_the_pipeline(client: AsyncTestClient[Litestar]) -> None:
    await login(client, ADMIN)
    use_company(client, "PURE Education")
    created = await client.post(
        "/api/crm/leads", json={"name": unique("Su Su"), "company": "ABC", "email": "su@example.com"}
    )
    assert created.status_code == 201, created.text
    lead = created.json()
    assert lead["status"] == "Open" and lead["dealId"] is None and lead["business"] == "PURE Education"

    # Leads and students are separate lists.
    listed = (await client.get("/api/crm/leads", params={"search": lead["name"].split()[-1]})).json()
    assert [row["id"] for row in listed["items"]] == [lead["id"]]
    students = (await client.get("/api/crm/contacts", params={"search": lead["name"].split()[-1]})).json()
    assert students["total"] == 0

    assert (await client.patch(f"/api/crm/leads/{lead['id']}", json={"status": "Contacted"})).json()[
        "status"
    ] == "Contacted"
    refused = await client.patch(f"/api/crm/leads/{lead['id']}", json={"status": "In Pipeline"})
    assert refused.status_code == 400

    # "New" puts it on the pipeline's New stage, once.
    moved = await client.patch(f"/api/crm/leads/{lead['id']}", json={"status": "New"})
    assert moved.status_code == 200, moved.text
    body = moved.json()
    assert body["status"] == "In Pipeline" and body["stage"] == "New" and body["dealId"]
    again = (await client.patch(f"/api/crm/leads/{lead['id']}", json={"status": "New"})).json()
    assert again["dealId"] == body["dealId"]
    stages = (await client.get("/api/crm/pipeline")).json()
    new_stage = next(st for st in stages if st["name"] == "New")
    cards = [d for d in new_stage["deals"] if d["contactId"] == lead["id"]]
    assert len(cards) == 1 and cards[0]["name"] == lead["name"] and cards[0]["company"] == "ABC"
    notes = (await client.get(f"/api/crm/deals/{body['dealId']}/messages", params={"kind": "note"})).json()
    assert any(n["body"] == "Moved here from Leads" for n in notes)
    in_pipeline = (await client.get("/api/crm/leads", params={"status": "In Pipeline"})).json()
    assert lead["id"] in {row["id"] for row in in_pipeline["items"]}

    # Removing the card puts the lead back to Open.
    assert (await client.delete(f"/api/crm/deals/{body['dealId']}")).status_code == 204
    back = (await client.get(f"/api/crm/leads/{lead['id']}")).json()
    assert back["status"] == "Open" and back["dealId"] is None

    # Created straight as "New": goes to the pipeline right away. Deleting the lead removes its card.
    direct = (await client.post("/api/crm/leads", json={"name": unique("Ko Ko"), "status": "New"})).json()
    assert direct["status"] == "In Pipeline" and direct["dealId"]
    assert (await client.delete(f"/api/crm/leads/{direct['id']}")).status_code == 204
    assert (await client.get(f"/api/crm/deals/{direct['dealId']}")).status_code == 404

    # Each company has its own leads.
    use_company(client, "GPM")
    assert (await client.get(f"/api/crm/leads/{lead['id']}")).status_code == 404


async def test_contact_list_is_students(client: AsyncTestClient[Litestar]) -> None:
    await login(client, ADMIN)
    student = (await client.post("/api/crm/contacts", json={"name": unique("Student")})).json()
    assert student["status"] == "Active"
    assert (await client.post("/api/crm/contacts", json={"name": "X", "status": "Lead"})).status_code == 400
    assert (await client.get(f"/api/crm/leads/{student['id']}")).status_code == 404
