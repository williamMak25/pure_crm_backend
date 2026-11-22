# PURE ERP API

Backend for the PURE Education ERP admin dashboard (`../pure-erp`).

**Stack:** Litestar 2 · Advanced Alchemy (SQLAlchemy 2 async, asyncpg) · Alembic · PostgreSQL 17 · Docker · uv

Built from the backend half of [litestar-fullstack](https://github.com/litestar-org/litestar-fullstack), without the Vite frontend, SAQ worker, email, OAuth, MFA or teams.

## Quick start (Docker)

The API and Postgres both run in containers. A one-shot `migrate` container applies migrations and seeds the data (company, businesses, roles, pipeline stages, and the admin from `SEED_ADMIN_*`) before the API starts.

```bash
cp .env.example .env    # set SECRET_KEY and SEED_ADMIN_EMAIL / SEED_ADMIN_PASSWORD

docker compose -f docker-compose.dev.yml up -d --build   # development: live reload
docker compose up -d --build                             # production image
```

| | `docker-compose.dev.yml` | `docker-compose.yml` |
| --- | --- | --- |
| Image | `dev` target, includes pytest and ruff | `prod` target, runtime dependencies only |
| Code | `./src` and `./tests` mounted, reloads on save | baked into the image |
| Rebuild when | `pyproject.toml` / `uv.lock` change | any code change |

Both use the same database volume, ports (API `8100`, Postgres `5434`) and seed. Run one at a time.

Common dev commands (use `docker compose` without `-f` for prod):

```bash
docker compose -f docker-compose.dev.yml logs -f api
docker compose -f docker-compose.dev.yml exec api pytest -q
docker compose -f docker-compose.dev.yml exec api ruff check src tests
docker compose -f docker-compose.dev.yml exec api app seed
docker compose -f docker-compose.dev.yml run --rm --no-deps --user "$(id -u):$(id -g)" api \
  app database make-migrations --autogenerate --no-prompt -m "add foo"
docker compose -f docker-compose.dev.yml exec db psql -U pure -d pure_erp
docker compose -f docker-compose.dev.yml down        # add -v to delete the database
```

API docs: http://localhost:8100/schema (Scalar UI).

## Without Docker for the API (Postgres still in Docker)

```bash
docker compose up -d db
uv sync
uv run app database upgrade --no-prompt
uv run app seed --admin-email admin@example.com --admin-password 'ChangeMe!2026'
uv run app run --reload --port 8100
uv run pytest                      # uses a separate pure_erp_test database
```

The frontend's Vite dev server proxies `/api` to `http://localhost:8100` (override with `API_PROXY_TARGET`), so `../pure-erp/.env` keeps `API_BASE_URL=/api` and the session cookies are same-origin. With `API_MOCK=true`, only the paths in `LIVE_PREFIXES` (`src/lib/constants/endpoints.ts`) hit this API; add a module there once its endpoints exist here.

## Commands

| Command | What it does |
| --- | --- |
| `app run --reload` | Start the API |
| `app database make-migrations --autogenerate -m "msg"` | Create a migration from model changes |
| `app database upgrade --no-prompt` | Apply migrations |
| `app database downgrade base --no-prompt` | Roll back everything |
| `app seed` | Company, the three business units, default roles and an optional admin. Safe to run again. |
| `app users create --email … --name … --role Sales --business pure-education` | Create a user (prompts for password) |

## Auth

Sessions use two **httpOnly cookies**, so page scripts never see a token:

| Cookie | Lifetime | Path | Purpose |
| --- | --- | --- | --- |
| `access_token` | 30 min (`ACCESS_TOKEN_EXPIRE_MINUTES`) | `/` | JWT checked on every request |
| `refresh_token` | 7 days (`REFRESH_TOKEN_EXPIRE_DAYS`) | `/api/auth` | Gets a new access token |

| Endpoint | Auth | Notes |
| --- | --- | --- |
| `POST /api/auth/login` | public | `{email, password}` → user + cookies |
| `POST /api/auth/refresh` | refresh cookie | Rotates the refresh token. Replaying an old one revokes the whole session. |
| `POST /api/auth/logout` | public | Revokes this session, clears cookies |
| `GET /api/me` | access cookie | `UserSummary` + `isSuperuser` + `permissions` (`{module: [actions]}`) |
| `GET /api/businesses` | access cookie | Business units the user can switch to (admins see all) |
| `GET /health` | public | Database check |

The user is loaded from the database on every request, so setting a user to Inactive locks them out right away.

The frontend has a `/login` page, and `src/lib/services/http.ts` calls `POST /auth/refresh` once on a 401, retries the request, and sends the browser to `/login` if that fails too.

### Permissions

Roles hold a permission matrix of module × action (`overview, crm, projects, sales, invoices, finance, hr, settings` × `create, read, update, delete, approve`). Protect a route with:

```python
from app.domain.accounts.guards import requires_permission

@get("/crm/contacts", guards=[requires_permission(m.AppModule.CRM, m.PermissionAction.READ)])
```

Superusers pass every check. Users only see the businesses they're linked to in `user_business`.

## CRM

All under `/api/crm`, guarded by the CRM row of the permission matrix (read / create / update / delete).

| Endpoint | Notes |
| --- | --- |
| `GET /contacts` · `/universities` · `/consultants` | `Paginated<T>`. Query: `page`, `pageSize` (≤100), `search`, `business`, `status` |
| `POST` same paths | `business` may be the name ("PURE Education"), slug or id |
| `GET` · `PATCH` · `DELETE /{collection}/{id}` | Rows in a business you can't access return 404 |
| `GET /pipeline?business=…` | Stages in order, each with `deals`, `total` (sum of amounts) and `progress` (share of deals) |
| `POST /pipeline` · `PATCH` · `DELETE /pipeline/{id}` | Add, rename/recolor/reorder, delete stage (409 while it still has deals) |
| `POST /pipeline/{stageId}/deals` | New card. Without `contactId` a Lead contact is created too |
| `GET` · `PATCH` · `DELETE /deals/{id}` | The "Edit Pipeline" dialog: contact, email, phone, social link, created on, consultant, saleperson, expected closing, tags, universities. `stageId` / `position` move the card and log a stage-change note |
| `GET` · `POST /deals/{id}/messages` | Timeline. `kind=message` (Send Message: To/Subject, recorded but not emailed) or `kind=note` (Long Note). `?kind=` and `?search=` filter |
| `GET` · `POST /deals/{id}/activities` | Planned activities: To Do, Email, Call, Meeting, Document, Signature |
| `PATCH` · `DELETE /deal-activities/{id}` | Edit, mark done (`{"done": true}`), remove |
| `GET /people?business=…` | Active users in a business, for the Saleperson / Assigned to pickers |

`owner` fields take a user's id or full name, must be someone who works in that business, and default to the signed-in user. `app seed` creates the New → Contacted → Qualified → Won stages for each business.

Shared helpers for the next modules are in `domain/organization/scope.py`: `provide_list_query`, `list_scoped`, `get_scoped`, `resolve_business`, `resolve_user`.

## Project & Board

All under `/api/projects`, guarded by the Projects row of the permission matrix, plus per-board access:

- **Private** boards are visible to their members only. **Workspace/public** boards are visible to everyone in the business.
- **Editing** (lists, cards) needs the Projects `update` permission and Admin/Member access on the board. Viewers can read and comment.
- **Managing** (share, member access, visibility, delete) needs Admin access on the board. Creators start as Admin, and a board always keeps at least one Admin.
- Board **status** and **due date** come from the cards: Planning → In Progress (a card is complete) → Completed (all cards complete); the due date is the latest card due date.

| Endpoint | Notes |
| --- | --- |
| `GET` · `POST /boards` | `Paginated<Board>` (`search`, `business`, `status`). New boards get To Do / In Progress / Review / Pending Tasks |
| `GET` · `PATCH` · `DELETE /boards/{id}` | Board view with lists, cards, members, `canEdit`, `canManage`. PATCH: `title`, `visibility` |
| `POST /boards/{id}/members` · `PATCH` · `DELETE /board-members/{id}` | Share by email/name/id, change access, remove |
| `GET /boards/{id}/candidates` | People in the business not yet on the board |
| `POST /boards/{id}/lists` · `PATCH` · `DELETE /lists/{id}` | Add, rename/reorder, delete (with its cards) |
| `POST /lists/{id}/tasks` | Add a card at the bottom |
| `GET` · `PATCH /tasks/{id}` | Open card: title, description, cover, labels, due date, members, `completed` |
| `POST /tasks/{id}/move` · `/copy` · `/archive` | Move to any list you can edit (`top`/`bottom`), copy, archive |
| `POST /tasks/{id}/checklist` · `PATCH` · `DELETE /checklist-items/{id}` | Checklist |
| `GET` · `POST /tasks/{id}/comments` | Comments (Viewers too) |

## Database

42 tables across organization, accounts, CRM, projects, sales, invoices, finance and HR. Conventions:

- UUIDv7 primary keys, `created_at` / `updated_at` on every table
- `business_id` on every operational table (`BusinessScopedMixin`)
- Money is `numeric(14,2)`; status columns are per-table Postgres enums holding the exact strings the UI shows
- Document numbers (`SO-0001`) come from `document_sequence`, never `count(*)`
- `citext` for emails, `pg_trgm` GIN indexes for name search

## Layout

```
src/app/
├── server/        app factory and core plugin (routes, auth, CORS, errors)
├── lib/           settings, crypto, schema base, error format
├── db/models/     one file per domain
├── db/migrations/ alembic
├── domain/        accounts (auth, users, roles), organization (+ business scoping), crm, projects, system
└── cli/           seed and users commands
```

Add each new domain (crm, sales…) as `domain/<name>/` with controllers, services and schemas, then register its controllers in `server/core.py`.
