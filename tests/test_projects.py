from __future__ import annotations

from typing import TYPE_CHECKING

from tests.conftest import ADMIN, SALES
from tests.test_auth import login
from tests.test_crm import unique

if TYPE_CHECKING:
    from litestar import Litestar
    from litestar.testing import AsyncTestClient


async def make_board(client: AsyncTestClient[Litestar], **extra: str) -> dict:
    created = await client.post(
        "/api/projects/boards", json={"title": unique("Website Redesign"), "business": "PURE Education", **extra}
    )
    assert created.status_code == 201, created.text
    return (await client.get(f"/api/projects/boards/{created.json()['id']}")).json()


async def test_board_lists_cards_and_status(client: AsyncTestClient[Litestar]) -> None:
    await login(client, ADMIN)
    board = await make_board(client)
    assert [lst["title"] for lst in board["lists"]] == ["To Do", "In Progress", "Review", "Pending Tasks"]
    assert board["status"] == "Planning" and board["canEdit"] and board["canManage"]
    assert board["members"][0]["access"] == "Admin"
    todo, doing = board["lists"][0], board["lists"][1]

    extra = await client.post(f"/api/projects/boards/{board['id']}/lists", json={"title": "My Projects"})
    assert extra.status_code == 201 and extra.json()["position"] == 4

    first = (await client.post(f"/api/projects/lists/{todo['id']}/tasks", json={"title": "Design homepage"})).json()
    second = (await client.post(f"/api/projects/lists/{todo['id']}/tasks", json={"title": "Write copy"})).json()
    me = board["members"][0]["id"]
    edited = await client.patch(
        f"/api/projects/tasks/{first['id']}",
        json={
            "labels": ["Design", "Urgent", "Design"],
            "dueDate": "2026-10-29",
            "memberIds": [me],
            "description": "Hero, nav and footer",
            "cover": "/images/task-cover.png",
            "completed": True,
        },
    )
    assert edited.status_code == 200, edited.text
    detail = edited.json()
    assert detail["labels"] == ["Design", "Urgent"]
    assert detail["assignee"]["id"] == me
    assert detail["completed"] and detail["hasDescription"] and detail["listTitle"] == "To Do"

    listed = (await client.get("/api/projects/boards", params={"search": board["title"].split()[-1]})).json()
    row = listed["items"][0]
    assert row["taskCount"] == 2 and row["status"] == "In Progress" and row["dueDate"] == "2026-10-29"
    in_progress = (await client.get("/api/projects/boards", params={"status": "In Progress"})).json()
    assert board["id"] in {b["id"] for b in in_progress["items"]}

    item = (await client.post(f"/api/projects/tasks/{second['id']}/checklist", json={"text": "Draft"})).json()
    await client.post(f"/api/projects/tasks/{second['id']}/checklist", json={"text": "Review"})
    await client.patch(f"/api/projects/checklist-items/{item['id']}", json={"done": True})
    card = (await client.get(f"/api/projects/tasks/{second['id']}")).json()
    assert (card["checklistDone"], card["checklistTotal"]) == (1, 2)
    assert (await client.delete(f"/api/projects/checklist-items/{item['id']}")).status_code == 204

    comment = await client.post(f"/api/projects/tasks/{second['id']}/comments", json={"body": "Looks good"})
    assert comment.status_code == 201
    assert (await client.get(f"/api/projects/tasks/{second['id']}/comments")).json()[0]["body"] == "Looks good"

    moved = await client.post(
        f"/api/projects/tasks/{second['id']}/move", json={"listId": doing["id"], "position": "top"}
    )
    assert moved.json()["listTitle"] == "In Progress"
    third = (await client.post(f"/api/projects/lists/{doing['id']}/tasks", json={"title": "Review copy"})).json()
    dropped = await client.post(f"/api/projects/tasks/{third['id']}/move", json={"listId": doing["id"], "position": 0})
    assert dropped.status_code == 201, dropped.text
    order = [t["title"] for t in (await client.get(f"/api/projects/boards/{board['id']}")).json()["lists"][1]["tasks"]]
    assert order == ["Review copy", "Write copy"]
    await client.post(f"/api/projects/tasks/{third['id']}/move", json={"listId": doing["id"], "position": 5})
    order = [t["title"] for t in (await client.get(f"/api/projects/boards/{board['id']}")).json()["lists"][1]["tasks"]]
    assert order == ["Write copy", "Review copy"]
    await client.post(f"/api/projects/tasks/{third['id']}/archive")
    copied = await client.post(f"/api/projects/tasks/{first['id']}/copy")
    assert copied.status_code == 201 and copied.json()["labels"] == ["Design", "Urgent"]
    assert (await client.post(f"/api/projects/tasks/{copied.json()['id']}/archive")).status_code == 204

    other = await make_board(client)
    across = await client.post(f"/api/projects/tasks/{first['id']}/move", json={"listId": other["lists"][2]["id"]})
    assert across.json()["boardId"] == other["id"]

    final = (await client.get(f"/api/projects/boards/{board['id']}")).json()
    titles = {lst["title"]: [t["title"] for t in lst["tasks"]] for lst in final["lists"]}
    assert titles["To Do"] == [] and titles["In Progress"] == ["Write copy"]

    renamed = await client.patch(f"/api/projects/lists/{extra.json()['id']}", json={"title": "Backlog"})
    assert renamed.json()["title"] == "Backlog"
    assert (await client.delete(f"/api/projects/lists/{extra.json()['id']}")).status_code == 204
    assert (await client.delete(f"/api/projects/boards/{other['id']}")).status_code == 204


async def test_board_sharing_and_access(client: AsyncTestClient[Litestar]) -> None:
    await login(client, ADMIN)
    board = await make_board(client)
    secret = await make_board(client, visibility="private")
    card = (await client.post(f"/api/projects/lists/{board['lists'][0]['id']}/tasks", json={"title": "Plan"})).json()

    candidates = (await client.get(f"/api/projects/boards/{board['id']}/candidates")).json()
    assert "Test Sales" in {c["name"] for c in candidates}
    shared = await client.post(
        f"/api/projects/boards/{board['id']}/members", json={"user": SALES[0], "access": "Viewer"}
    )
    assert shared.status_code == 201, shared.text
    member_id = shared.json()["memberId"]
    duplicate = await client.post(f"/api/projects/boards/{board['id']}/members", json={"user": "Test Sales"})
    assert duplicate.status_code == 400
    admin_member = board["members"][0]["memberId"]
    assert (
        await client.patch(f"/api/projects/board-members/{admin_member}", json={"access": "Member"})
    ).status_code == 400
    await client.post("/api/auth/logout")

    await login(client, SALES)
    assert (
        await client.post("/api/projects/boards", json={"title": "X", "business": "PURE Education"})
    ).status_code == 403
    assert (await client.get(f"/api/projects/boards/{secret['id']}")).status_code == 404
    view = (await client.get(f"/api/projects/boards/{board['id']}")).json()
    assert view["canEdit"] is False and view["canManage"] is False
    assert (await client.patch(f"/api/projects/tasks/{card['id']}", json={"title": "Nope"})).status_code == 403
    assert (
        await client.post(f"/api/projects/tasks/{card['id']}/comments", json={"body": "Viewer note"})
    ).status_code == 201
    visible = {b["id"] for b in (await client.get("/api/projects/boards", params={"pageSize": 100})).json()["items"]}
    assert board["id"] in visible and secret["id"] not in visible
    await client.post("/api/auth/logout")

    await login(client, ADMIN)
    assert (
        await client.patch(f"/api/projects/board-members/{member_id}", json={"access": "Member"})
    ).status_code == 200
    await client.post("/api/auth/logout")

    await login(client, SALES)
    edited = await client.patch(f"/api/projects/tasks/{card['id']}", json={"title": "Plan v2"})
    assert edited.status_code == 200 and edited.json()["title"] == "Plan v2"
    assert (await client.patch(f"/api/projects/boards/{board['id']}", json={"visibility": "public"})).status_code == 403
