# Deploying RivalRadar

A step-by-step guide to putting RivalRadar online using only free tiers.

Nothing here has been deployed yet — this describes what to do with the
code as it now stands.

---

## Architecture

```
  Browser
     │
     ▼
  GitHub Pages ──────────►  Render (FastAPI)  ──────►  Supabase (PostgreSQL)
  static Next.js export      HTTPS, CORS-gated            │
                                     │                    │
                                     └──────►  OpenRouter (free model)
```

Two properties of this layout matter:

- **The OpenRouter key never leaves the backend.** The browser talks only to
  the RivalRadar API. There is no code path from the frontend to OpenRouter,
  and no `NEXT_PUBLIC_*` variable carries a credential.
- **GitHub Pages serves files, not a server.** The frontend is a static
  export, so it calls the Render backend across origins — which is why
  `CORS_ORIGINS` has to name the Pages origin exactly.

---

## Deploy in this order

The order matters: each step produces a value the next one needs.

1. Push to GitHub
2. Create the Supabase database → gives you `DATABASE_URL`
3. Create the Render service with that `DATABASE_URL` → gives you the API URL
4. Set the API URL as a GitHub repository variable
5. Enable GitHub Pages → gives you the site origin
6. Put the site origin into Render's `CORS_ORIGINS` and redeploy
7. Verify

Steps 3 and 6 are two separate visits to Render. That is unavoidable: Render
needs the database before it can boot, and it cannot know the Pages origin
until Pages exists.

---

## 1. Push to GitHub

The project is not a git repository yet.

```bash
cd "C:/Users/Shreyas Tiwari/Downloads/RivalRadar/rivalradar"
git init
git branch -M main
git add .
git status          # confirm no .env and no *.db are staged
git commit -m "RivalRadar: AI competitor intelligence"
```

Create an **empty** repository on GitHub (no README, no .gitignore), then:

```bash
git remote add origin https://github.com/YOUR_USERNAME/rivalradar.git
git push -u origin main
```

Before pushing, confirm the secrets really are excluded:

```bash
git ls-files | grep -E "\.env$|\.env\.|\.db$" || echo "clean - no secrets staged"
```

That must print `clean`. `.env.example` files *are* committed; they contain no
values.

---

## 2. Supabase — PostgreSQL

1. Sign in at <https://supabase.com> → **New project** (Free plan).
2. Name it `rivalradar`. For the database password use **letters and numbers
   only**. Symbols such as `@ : / ? # %` have to be percent-encoded inside a
   URL, and getting that wrong is the most common cause of "password
   authentication failed". **Save the password in a password manager now** —
   Supabase does not show it again.
3. Region: **Southeast Asia (Singapore)** — the same region as the Render
   service (`region: singapore` in `render.yaml`).
4. Wait for provisioning (~2 minutes).
5. Click **Connect** at the top of the project page → **Connection String** →
   Method: **Session pooler**. Copy the URI. It ends in
   `.pooler.supabase.com:5432/postgres`.

   Use the Session pooler, not:

   - **Direct connection** — that host is IPv6-only, and Render's outbound
     network is IPv4-only, so it can never connect from Render.
   - **Transaction pooler** (port `6543`) — built for short-lived serverless
     functions. A long-running server like this one belongs on the session
     pooler, which also speaks IPv4.

6. Replace `[YOUR-PASSWORD]` — brackets included — with your password, and
   add `?sslmode=require` to the end so the connection can never fall back to
   plaintext:

   ```
   postgresql://postgres.abcdefghijkl:YOUR_PASSWORD@aws-1-ap-southeast-1.pooler.supabase.com:5432/postgres?sslmode=require
   ```

   The user is `postgres.<project-ref>`, not plain `postgres`: the pooler
   uses the suffix to find your project.

You do **not** need to create any tables by hand. Alembic creates them —
either when Render starts, or beforehand from your own machine with
`scripts/check_database.py` (see [Database migrations](#database-migrations)).

---

## 3. Render — the backend

### Option A — from the blueprint (recommended)

1. <https://dashboard.render.com> → **New → Blueprint**.
2. Connect the repository. Render reads `render.yaml` and proposes a free web
   service named `rivalradar-api`.
3. It will prompt for the three values marked `sync: false`. Fill them in:

   | Variable             | Value                                                   |
   | -------------------- | ------------------------------------------------------- |
   | `DATABASE_URL`       | the Supabase URI from step 2                              |
   | `OPENROUTER_API_KEY` | your key from <https://openrouter.ai/keys>                |
   | `CORS_ORIGINS`       | `http://localhost:3000` for now — corrected in step 6     |

4. **Apply**. The build installs dependencies. Then the start command runs
   `alembic upgrade head` against Supabase and, only if that succeeds, starts
   uvicorn.

   There is no pre-deploy command: Render offers `preDeployCommand` only on
   paid plans and rejects a free blueprint that declares one. On a database
   that is already up to date the upgrade does nothing and takes about a
   second per cold start.

### Option B — manual service

New → Web Service → connect the repo, then:

- **Root directory:** `backend`
- **Runtime:** Python 3
- **Region:** Singapore (it cannot be changed after creation)
- **Build command:** `pip install --upgrade pip && pip install -r requirements.txt`
- **Pre-deploy command:** leave empty — not available on the free plan
- **Start command:** `alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port $PORT --workers 1`
- **Health check path:** `/health`
- **Plan:** Free

Then add every environment variable listed in `render.yaml` by hand.

### Confirm it booted

```bash
curl https://YOUR-SERVICE.onrender.com/health
```

Expected:

```json
{
  "status": "ok",
  "environment": "production",
  "database": { "backend": "postgresql", "connected": true },
  "llm_provider": "openrouter",
  "demo_mode": false,
  "scheduler_enabled": false
}
```

The first request after a period of inactivity takes 30–60 seconds: free
instances sleep and must cold-start. That is the platform, not a bug.

**Copy the service URL.** You need it next.

---

## 4. Tell the frontend where the backend is

In the GitHub repository: **Settings → Secrets and variables → Actions →
Variables → New repository variable**.

| Name                  | Value                                   |
| --------------------- | --------------------------------------- |
| `NEXT_PUBLIC_API_URL` | `https://YOUR-SERVICE.onrender.com`     |

A **variable**, not a secret. This URL is compiled into the JavaScript bundle
and is public by nature; storing it as a secret only masks it in build logs
and makes failures harder to read.

No trailing slash.

---

## 5. GitHub Pages

1. **Settings → Pages → Build and deployment → Source: GitHub Actions.**
2. Run the workflow: **Actions → "Deploy frontend to GitHub Pages" → Run
   workflow**. (It also runs automatically on every push that touches
   `frontend/`.)

The workflow works out the base path itself:

- repository named `YOUR_USERNAME.github.io` → site at the domain root, no
  base path
- any other name → project site at `/<repo>/`, base path set accordingly

When it finishes, the site is at:

```
https://YOUR_USERNAME.github.io/rivalradar/
```

It will load but every panel will show a connection error. That is step 6.

---

## 6. CORS — let the site call the API

Back in Render → your service → **Environment** → edit `CORS_ORIGINS`:

```
https://YOUR_USERNAME.github.io
```

The **origin only**: scheme and host, no path, no trailing slash. A project
site at `https://you.github.io/rivalradar/` still has the origin
`https://you.github.io`.

To keep local development working too, list both, comma separated:

```
https://YOUR_USERNAME.github.io,http://localhost:3000
```

Save. Render restarts automatically. `*` is rejected outright in production —
this API has no authentication, so a wildcard would let any website drive it
from a visitor's browser.

---

## 7. Verify

```bash
python scripts/verify_production.py https://YOUR-SERVICE.onrender.com \
    --origin https://YOUR_USERNAME.github.io
```

This checks the health endpoint, the database connection and driver, that no
credentials appear in any response, that demo mode is off and no fictional
competitors exist, that OpenRouter is configured with a pinned model, and that
CORS allows your origin and is not a wildcard.

To also prove the scraper, the diff engine and OpenRouter work end to end —
one real scan, one free-tier LLM call, real records written:

```bash
python scripts/verify_production.py https://YOUR-SERVICE.onrender.com --scan
```

Then in the browser: open the site, add a competitor, run a scan, and confirm
a change appears with a real analysis attached.

---

## Environment variables

### Backend (Render dashboard)

| Variable             | Required | Value                                              |
| -------------------- | -------- | -------------------------------------------------- |
| `DATABASE_URL`       | **yes**  | Supabase URI. Startup fails without it in production |
| `OPENROUTER_API_KEY` | **yes**  | From openrouter.ai/keys. Backend only               |
| `CORS_ORIGINS`       | **yes**  | Your Pages origin, comma separated                  |
| `ENVIRONMENT`        | yes      | `production`                                        |
| `DEBUG`              | yes      | `false`                                             |
| `DEMO_MODE`          | yes      | `false`                                             |
| `LLM_PROVIDER`       | yes      | `openrouter`                                        |
| `OPENROUTER_MODEL`   | yes      | `deepseek/deepseek-v4-flash-0731:free`              |
| `SCHEDULER_ENABLED`  | yes      | `false` — see below                                 |
| `PLAYWRIGHT_ENABLED` | yes      | `false` — see below                                 |

All of these except the first three are already set by `render.yaml`.

### Frontend (GitHub repository variable)

| Variable                 | Required | Value                        |
| ------------------------ | -------- | ---------------------------- |
| `NEXT_PUBLIC_API_URL`    | **yes**  | Render service URL           |
| `NEXT_PUBLIC_BASE_PATH`  | no       | Set automatically by CI      |

Never put a key in a `NEXT_PUBLIC_*` variable. Everything with that prefix is
readable by anyone who opens the site.

---

## Database migrations

The production schema is owned by Alembic. `create_all()` is deliberately not
used there: it would build tables behind the migration history's back and
leave `alembic_version` empty, after which every later migration either fails
or silently skips. The app refuses to start against an unmigrated production
database and says so.

On Render the migration runs at the start of every boot, as part of the start
command (the free plan has no pre-deploy step). It is a no-op once the
database is current.

```bash
cd backend

# Apply everything (Render does this itself every time the service starts)
alembic upgrade head

# Roll back one revision
alembic downgrade -1

# Where are we?
alembic current

# After changing a model
alembic revision --autogenerate -m "describe the change"
alembic check          # confirms models and migrations agree
```

To migrate and verify the Supabase database from your own machine — before
Render exists, or at any time after — run the check script from the
repository root:

```powershell
.\backend\.venv\Scripts\python.exe .\scripts\check_database.py
```

It asks for the connection string at a hidden prompt, so the password never
lands in your shell history, and it never prints the password or the full
URL. It validates the URL, runs `alembic upgrade head` and `alembic check`,
boots the app's own database layer in production mode, and reports SSL, the
schema revision, the tables, and whether Supabase's public `anon` role can
read them.

Do **not** put the Supabase URL in `backend/.env`. The local dev server runs
in development mode, where the schema is created with `create_all()` rather
than through Alembic — pointed at Supabase, that would bypass the migration
history.

Locally, with no `DATABASE_URL`, everything targets `backend/rivalradar.db`.

---

## Two things this deployment does *not* do

### The scheduler is off

`SCHEDULER_ENABLED=false`, deliberately. A free Render instance sleeps after
about fifteen minutes of inactivity. A background scheduler would therefore
run only while somebody happened to be using the site — so the dashboard
would be claiming continuous monitoring that is not happening.

Scans are manual: the "Run scan" button, or `POST /api/competitors/{id}/scan`.

To get real scheduled monitoring, either upgrade to a paid Render instance
that does not sleep, or drive scans externally — a GitHub Actions cron job
that POSTs to the scan endpoint works well and stays free.

### JavaScript rendering is off

`PLAYWRIGHT_ENABLED=false`. Chromium is roughly 400 MB installed, against a
512 MB free instance, and the build would likely fail or the process would be
OOM-killed at runtime.

Normal HTTPX scraping is unaffected and handles server-rendered pages — which
is most pricing, careers and product pages. Single-page apps that render
entirely client-side will return little content.

To enable it anyway on a paid instance, change the build command to
`pip install -r requirements.txt -r requirements-playwright.txt && playwright install --with-deps chromium`
and set `PLAYWRIGHT_ENABLED=true`.

---

## Troubleshooting

**Every panel shows "Cannot reach the RivalRadar API"**

Open the browser console. A CORS message means `CORS_ORIGINS` does not match
your Pages origin exactly — check for a trailing slash or `http` vs `https`.
A 404 on `/api/...` means `NEXT_PUBLIC_API_URL` was not set when the site was
built; set the repository variable and re-run the workflow. A long pause
followed by success is just the free instance cold-starting.

**Render build fails on `psycopg`**

The `[binary]` extra should supply a prebuilt wheel. If your Python version
has no wheel, pin `PYTHON_VERSION` to `3.12.7` in the Render environment.

**`Production DATABASE_URL is required.`**

Working as intended: `ENVIRONMENT=production` with no `DATABASE_URL`. The
alternative would be a SQLite file on a container filesystem that is wiped on
every restart — data loss that looks like a healthy service.

**`The production database has no schema.`**

`alembic upgrade head` has not run. On Render, check that the start command
begins with `alembic upgrade head &&` — the free plan has no pre-deploy step,
so without it nothing creates the schema. Or migrate from your own machine
with `scripts/check_database.py`, then redeploy.

**`prepared statement "_pg3_0" does not exist`**

A pooled Supabase connection without prepared statements disabled. The app
sets `prepare_threshold=None` for `postgresql+psycopg://` URLs — this error
means the URL is using a different driver. Let the app normalise it: supply
the plain `postgresql://` form.

**Assets 404 on GitHub Pages**

The base path is wrong for the repository name. The workflow derives it
automatically; if you build by hand, set `NEXT_PUBLIC_BASE_PATH=/<repo>` for
a project site and leave it empty for a `<user>.github.io` site.

**Pages shows the README instead of the app**

Settings → Pages → Source must be **GitHub Actions**, not "Deploy from a
branch".

**A scan returns `unsafe_url`**

The SSRF guard rejected the target — a private, loopback or link-local
address. That guard is what stops a public deployment being used to probe
Render's internal network. Do not set `ALLOW_PRIVATE_NETWORKS=true` on a
public instance.

---

## Costs

| Service      | Plan | Limit that matters                                    |
| ------------ | ---- | ------------------------------------------------------ |
| GitHub Pages | Free | 1 GB site, 100 GB/month bandwidth                      |
| Render       | Free | 512 MB, sleeps after ~15 min idle, 750 hours/month     |
| Supabase     | Free | 500 MB database, paused after 7 days with no activity  |
| OpenRouter   | Free | Per-model rate limits on `:free` slugs                 |

Supabase pausing after a week of inactivity is worth knowing: the project
resumes from the dashboard, and no data is lost.
