# Replicon Timesheet Dashboard

Self-serve web app for filling and submitting weekly Replicon timesheets.

Each person **registers**, pastes their **Replicon access token once**, configures a **fill template** (task names + hours), then either:

- clicks **Run fill** on the dashboard, or
- enables a **schedule** (APScheduler, in-process)

No admin role. No AI / Cursor skills. One Python codebase with a **server-rendered** (Jinja2) UI.

---

## Quick start

```powershell
cd D:\Akash\replicon_automation
D:\Akash\.venv\Scripts\python.exe -m pip install -r requirements.txt
copy .env.example .env
# Edit .env and set a strong SECRET_KEY

D:\Akash\.venv\Scripts\python.exe -m uvicorn app.main:app --reload
```

Open [http://127.0.0.1:8000](http://127.0.0.1:8000):

1. **Register** a dashboard account  
2. **Setup** — paste Replicon base URL, user URI, access token (validated with a live inspect)  
3. Review the seeded **Default 9h** template (Coding / Management / Meetings @ 3h)  
4. On **Overview**, pick a week date + template → **Fill & submit**  
5. Optionally add a **Schedule** (weekday + UTC time)

SQLite file defaults to `data/replicon_dashboard.db`.

Legacy JSON endpoints remain under `/timesheets/*` and `/docs` (they still use `REPLICON_ACCESS_TOKEN` from `.env` if set). Prefer the dashboard for day-to-day use.

---

## Architecture

```
Browser (Jinja pages)
    │
    ▼
FastAPI routes (app/api/*)          ← HTTP / forms only
    │
    ▼
Services (app/services/*)           ← business rules
    │
    ├── Repositories (app/repositories/*) → SQLite
    └── TimesheetService → RepliconClient → na5.replicon.com
                ▲
         Factory builds client from
         that user's encrypted token
```

APScheduler loads enabled `ScheduledJob` rows on startup and calls the same `WeeklyFillService` path as the UI button.

---

## Design patterns (why)

| Pattern | Where | Why we used it |
|---------|-------|----------------|
| **Layered architecture** | `api` → `services` → `repositories` / `clients` | Keeps HTTP, business rules, and persistence separable so UI changes do not break Replicon logic. |
| **Repository** | [`app/repositories/`](app/repositories/) | All SQL lives here. Swapping SQLite for Postgres later should not touch `WeeklyFillService`. |
| **Dependency Injection** | [`app/dependencies.py`](app/dependencies.py) | Routes declare `Depends(get_db)`, `get_current_user`, etc. Tests can override providers without monkey-patching globals. |
| **Factory** | [`app/services/client_factory.py`](app/services/client_factory.py) | Each user has their own token. The factory builds a `RepliconClient` from decrypted credentials instead of a single env token. |
| **Facade** | [`app/services/weekly_fill_service.py`](app/services/weekly_fill_service.py) | One method (`run_week`) hides inspect → skip days → N× time-entry → submit → history. Replaces the old AI/fill_prompt orchestration. |
| **Template Method / Strategy data** | `FillTemplate` + `TemplateTask` | Fill algorithm is fixed; task names, hours, and skip flags are per-user data so others customize without code changes. |
| **Encrypted secret at rest** | [`app/security/crypto.py`](app/security/crypto.py) | Fernet key derived from `SECRET_KEY`. Tokens are never rendered back into HTML. |

Comments in those modules repeat the same rationale so maintainers see intent next to the code.

---

## Main pages

| Path | Purpose |
|------|---------|
| `/register`, `/login` | Dashboard accounts |
| `/setup` | One-time Replicon URI + token |
| `/` | Month week statuses + Run fill |
| `/templates` | CRUD fill templates |
| `/schedules` | Enable/disable weekday+UTC jobs |
| `/history` | Past fill runs |

---

## Security notes (pragmatic)

- Passwords hashed with bcrypt (`passlib`)
- Replicon tokens encrypted with Fernet (`SECRET_KEY`)
- Session cookie: `HttpOnly`, `SameSite=Lax`
- Repositories always filter by `user_id` — no cross-user access
- Change `SECRET_KEY` before real use; rotating it invalidates encrypted tokens (users re-enter on Setup)

---

## Tests

```powershell
D:\Akash\.venv\Scripts\python.exe -m pytest -q
```

Unit tests mock Replicon. Dashboard tests use an in-memory SQLite database.

---

## Docker

```powershell
docker build -f docker/Dockerfile -t replicon-dashboard .
docker run -p 8000:8000 -e SECRET_KEY=your-secret -v replicon-data:/data replicon-dashboard
```

---

## Project layout

```
app/
  api/           # HTTP routes (HTML forms + legacy JSON)
  clients/       # Replicon HTTP client
  db/            # SQLAlchemy models + session
  models/        # Pydantic request/response for JSON API
  repositories/  # Persistence
  security/      # Passwords + token encryption
  services/      # Auth, credentials, weekly fill, scheduler
  web/           # Jinja templates + static CSS/JS
```
