#!/usr/bin/env python3
r"""Create and verify the RivalRadar schema on Supabase.

Run it yourself, in your own terminal, from the repository root:

    .\backend\.venv\Scripts\python.exe .\scripts\check_database.py

It reads DATABASE_URL if that is already set in the terminal; otherwise it asks
for the connection string at a hidden prompt. Then it:

  1. checks the URL's shape before connecting, and explains any problem;
  2. connects, and reports the server version and SSL;
  3. runs `alembic upgrade head` and `alembic check`;
  4. boots the app's own database layer in production mode (init_db);
  5. lists the tables, and checks that Supabase's public `anon` role cannot
     read them.

The password and the full URL are never printed. As a second line of defence,
everything this process writes to the terminal passes through a redacting
filter, so not even an unexpected library message can echo them.

ENVIRONMENT=production and DATABASE_URL are set for this process only; nothing
is written to disk and the terminal's own environment is left untouched.

Exit code 0: every check passed (warnings allowed). Exit code 1: something failed.
"""

from __future__ import annotations

import contextlib
import getpass
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TextIO
from urllib.parse import parse_qs, quote, unquote, urlsplit

REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND = REPO_ROOT / "backend"

POOLER_SUFFIX = ".pooler.supabase.com"
SESSION_POOLER_PORT = 5432
TRANSACTION_POOLER_PORT = 6543
# Characters that cannot appear unencoded in a URL password.
URL_BREAKING = "@/?#[]"

ANON_FIX = """\
If the Data API is on, anyone holding the project's public anon key can read
this table. RivalRadar never uses the Data API, so remove the access.
Supabase -> SQL Editor -> run:
  REVOKE ALL ON ALL TABLES IN SCHEMA public FROM anon, authenticated;
  REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM anon, authenticated;
  ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE ALL ON TABLES FROM anon, authenticated;
  ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE ALL ON SEQUENCES FROM anon, authenticated;
Then run this script again."""

# (text found in a driver error, plain-words explanation)
HINTS: tuple[tuple[str, str], ...] = (
    (
        "password authentication failed",
        "The password is wrong. Check it against your password manager, or reset it:\n"
        "Supabase -> Project Settings -> Database -> Reset database password,\n"
        "then rebuild the URL with the new password.",
    ),
    (
        # Supavisor words this "tenant/user <user> not found".
        "tenant",
        "The pooler does not recognise this user. The part after 'postgres.' must be\n"
        "your project ref, and the host must come from the same Connect dialog.\n"
        "A project that is still starting, or is paused, gives this too - wait a\n"
        "minute and retry.",
    ),
    (
        "timeout",
        "No answer in time. The project may still be starting (wait a minute), or a\n"
        "firewall/VPN on this machine is blocking outbound port 5432.",
    ),
    (
        "could not translate host name",
        "The host name does not exist. Copy the URI again from\n"
        "Connect -> Connection String -> Method: Session pooler.",
    ),
    (
        "getaddrinfo",
        "The host name does not exist. Copy the URI again from\n"
        "Connect -> Connection String -> Method: Session pooler.",
    ),
    (
        "connection refused",
        "The server refused the connection. Check the port is 5432 and the host is\n"
        "the Session pooler host.",
    ),
    (
        "max client connections",
        "The pooler is at its connection limit. Wait a minute and retry.",
    ),
)


# ---------------------------------------------------------------------------
# Redaction
# ---------------------------------------------------------------------------

_secrets: list[tuple[str, str]] = []


def protect(value: str | None, replacement: str) -> None:
    """Register a string that must never reach the terminal."""
    if not value:
        return
    for variant in {value, unquote(value), quote(value, safe="")}:
        if variant and all(variant != known for known, _ in _secrets):
            _secrets.append((variant, replacement))
    # Longest first, so a URL is replaced whole before its password is.
    _secrets.sort(key=lambda pair: len(pair[0]), reverse=True)


def redact(text: str) -> str:
    for secret, replacement in _secrets:
        if secret in text:
            text = text.replace(secret, replacement)
    return text


class RedactingStream:
    """Wraps stdout/stderr so nothing registered with protect() is written."""

    def __init__(self, inner: TextIO) -> None:
        self._inner = inner

    def write(self, text: str) -> int:
        self._inner.write(redact(text))
        return len(text)

    def flush(self) -> None:
        self._inner.flush()

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)


def harden_console() -> None:
    for stream in (sys.stdout, sys.stderr):
        # Windows consoles default to cp1252; never crash on an odd character.
        with contextlib.suppress(AttributeError, ValueError, OSError):
            stream.reconfigure(errors="replace")
    sys.stdout = RedactingStream(sys.stdout)  # type: ignore[assignment]
    sys.stderr = RedactingStream(sys.stderr)  # type: ignore[assignment]


def describe(exc: BaseException) -> str:
    """Error type and message only: never a traceback, never a secret."""
    original = getattr(exc, "orig", None) or exc  # SQLAlchemy wraps driver errors
    message = " ".join(str(original).split())
    message = message.split(" (Background on this error at:")[0]
    # libpq tries every address the host resolves to and repeats the same
    # failure for each. The first one says everything.
    message = message.split(" Multiple connection attempts failed.")[0]
    if len(message) > 300:
        message = message[:297] + "..."
    return f"{type(original).__name__}: {redact(message) or '(no message)'}"


def hint_for(exc: BaseException) -> str:
    text = str(getattr(exc, "orig", None) or exc).lower()
    for needle, hint in HINTS:
        if needle in text:
            return hint
    return ""


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------


class Report:
    def __init__(self) -> None:
        self.failed = 0
        self.warned = 0

    def section(self, title: str) -> None:
        print(f"\n{title}", flush=True)

    def ok(self, message: str) -> None:
        self._emit("PASS", message)

    def info(self, message: str, detail: str = "") -> None:
        self._emit("INFO", message, detail)

    def warn(self, message: str, fix: str = "") -> None:
        self.warned += 1
        self._emit("WARN", message, fix)

    def fail(self, message: str, fix: str = "") -> None:
        self.failed += 1
        self._emit("FAIL", message, fix)

    def _emit(self, status: str, message: str, fix: str = "") -> None:
        print(f"  {status}  {message}", flush=True)
        for line in fix.splitlines():
            print(f"        {line}", flush=True)


# ---------------------------------------------------------------------------
# 1. Read and check the URL, without connecting
# ---------------------------------------------------------------------------


@dataclass
class Target:
    url: str
    host: str
    port: int
    masked_user: str


def read_url() -> tuple[str, str] | None:
    from_env = os.environ.get("DATABASE_URL", "")
    if from_env.strip():
        return from_env, "the DATABASE_URL environment variable"
    try:
        entered = getpass.getpass(
            "Paste the Session pooler connection string and press Enter\n"
            "(nothing appears while you paste - that is normal): "
        )
    except (EOFError, KeyboardInterrupt):
        print(flush=True)
        return None
    return entered, "the hidden prompt"


def mask_ref(ref: str) -> str:
    return f"{ref[:3]}***{ref[-3:]}" if len(ref) > 6 else f"{ref[:1]}***"


def clean(raw: str) -> str:
    url = raw.strip()
    if url.upper().startswith("DATABASE_URL="):
        url = url[len("DATABASE_URL=") :].strip()
    if len(url) >= 2 and url[0] == url[-1] and url[0] in "\"'":
        url = url[1:-1].strip()
    return url


def register_secrets(url: str) -> str:
    """Protect the URL and password before anything is printed. Returns the ref."""
    protect(url, "<DATABASE_URL>")
    rest = url.split("://", 1)[-1]
    # rsplit: a password containing '@' still leaves the host as the last part.
    userinfo = rest.rsplit("@", 1)[0] if "@" in rest else ""
    user, _, password = userinfo.partition(":")
    # The unfilled placeholder is Supabase's literal text, not a secret; masking
    # it would turn the explanation into "the placeholder *** is still there".
    if "YOUR-PASSWORD" not in password.upper():
        protect(password, "***")
    ref = user[len("postgres.") :] if user.startswith("postgres.") else ""
    if len(ref) > 2:
        protect(ref, mask_ref(ref))
    return password


def check_url(url: str, source: str, report: Report) -> Target | None:
    report.section("Connection string")
    report.info(f"read from {source}")

    if not url:
        report.fail("nothing was entered", "Run the script again and paste the URI.")
        return None

    password = register_secrets(url)

    # These two make Python's URL parser fail with a baffling message, so they
    # are caught first and explained in plain words.
    if "YOUR-PASSWORD" in url.upper():
        report.fail(
            "the placeholder [YOUR-PASSWORD] is still in the URL",
            "Replace [YOUR-PASSWORD] - brackets included - with your database password.",
        )
        return None
    if any(char.isspace() for char in url):
        report.fail(
            "the URL contains a space or a line break",
            "Copy it again as one unbroken line.",
        )
        return None
    if any(char in password for char in URL_BREAKING):
        report.fail(
            "the password contains a character that breaks URLs (@ / ? # [ ])",
            "Reset the password to letters and numbers only:\n"
            "Supabase -> Project Settings -> Database -> Reset database password.",
        )
        return None

    try:
        parts = urlsplit(url)
        host = (parts.hostname or "").lower()
        port = parts.port
        user = unquote(parts.username or "")
        query = parse_qs(parts.query)
    except ValueError as exc:
        report.fail(
            "the text could not be read as a URL",
            f"Copy the URI again from Connect -> Session pooler. ({type(exc).__name__})",
        )
        return None

    ref = user[len("postgres.") :] if user.startswith("postgres.") else ""
    masked_user = f"postgres.{mask_ref(ref)}" if ref else (user or "(none)")
    report.info(f"host: {host or '(none)'}")
    report.info(f"port: {port if port is not None else '(none)'}")
    report.info(f"user: {masked_user}")

    report.section("URL checks (nothing has been sent anywhere yet)")
    ok = True

    scheme = parts.scheme.lower().split("+", 1)[0]
    if scheme in {"postgres", "postgresql"}:
        report.ok(f"scheme is {scheme}://")
    else:
        ok = False
        report.fail(
            f"the URL starts with '{parts.scheme}://', not postgresql://",
            "Copy the URI (Connection String tab), not a JDBC or .NET string.",
        )

    if host.endswith(POOLER_SUFFIX):
        report.ok("host is a Supabase pooler (*.pooler.supabase.com)")
    elif host.startswith("db.") and host.endswith(".supabase.co"):
        ok = False
        report.fail(
            "this is the Direct connection host",
            "It is IPv6-only and Render is IPv4-only, so Render could never reach it.\n"
            "Use Connect -> Connection String -> Method: Session pooler.",
        )
    else:
        ok = False
        report.fail(
            "the host is not a Supabase pooler host",
            "It should end in .pooler.supabase.com. Copy the URI again from\n"
            "Connect -> Connection String -> Method: Session pooler.",
        )

    if port == SESSION_POOLER_PORT:
        report.ok("port 5432 (session pooler)")
    elif port == TRANSACTION_POOLER_PORT:
        ok = False
        report.fail(
            "port 6543 is the Transaction pooler",
            "Choose Method: Session pooler instead - it uses port 5432.",
        )
    else:
        ok = False
        report.fail(
            f"the port is {port if port is not None else 'missing'}, expected 5432",
            "Copy the Session pooler URI again; it ends in :5432/postgres.",
        )

    if ref:
        report.ok("user is postgres.<project-ref>")
    elif user == "postgres":
        ok = False
        report.fail(
            "the user is plain 'postgres'",
            "The pooler needs 'postgres.<project-ref>'. The plain form comes from the\n"
            "Direct connection string - use the Session pooler URI.",
        )
    else:
        ok = False
        report.fail(
            "the user does not start with 'postgres.'",
            "Copy the Session pooler URI again; its user is postgres.<project-ref>.",
        )

    if password:
        report.ok("password is filled in")
    else:
        ok = False
        report.fail(
            "there is no password in the URL",
            "It goes between 'postgres.<ref>:' and '@'.",
        )

    sslmode = query.get("sslmode", [""])[-1]
    if sslmode == "require":
        report.ok("sslmode=require")
    elif url.count("?") > 1:
        ok = False
        report.fail(
            "the URL has two '?' characters",
            "Only the first parameter starts with '?'; join the rest with '&'.",
        )
    elif sslmode:
        ok = False
        report.fail(
            f"sslmode is '{sslmode}'",
            "Set it to require: ...postgres?sslmode=require",
        )
    else:
        ok = False
        report.fail(
            "sslmode=require is missing",
            "Add ?sslmode=require to the end so the connection can never fall back\n"
            "to plaintext.",
        )

    if not ok:
        return None
    return Target(url=url, host=host, port=port or 0, masked_user=masked_user)


# ---------------------------------------------------------------------------
# 2. Connect
# ---------------------------------------------------------------------------


def prepare_process(url: str) -> None:
    """Configure this process only, then load the app from backend/."""
    # Fail in seconds rather than minutes on a wrong host. Used only by this
    # process; the URL you paste into Render is left exactly as you typed it.
    if "connect_timeout=" not in url:
        url = f"{url}&connect_timeout=15"
    protect(url, "<DATABASE_URL>")

    os.environ["DATABASE_URL"] = url
    os.environ["ENVIRONMENT"] = "production"
    # This check serves no HTTP. A fixed value keeps an unrelated CORS entry in
    # backend/.env from failing the production settings validation.
    os.environ["CORS_ORIGINS"] = "http://localhost:3000"

    sys.path.insert(0, str(BACKEND))
    os.chdir(BACKEND)  # alembic.ini uses paths relative to backend/


def check_connection(report: Report) -> tuple[bool, str | None]:
    """Returns (connected, alembic revision before the upgrade)."""
    report.section("Connection")
    try:
        from app.config.settings import settings

        protect(settings.database_url, "<DATABASE_URL>")
        from sqlalchemy import text

        from app.database.session import engine
    except Exception as exc:  # the app refused to load in production mode
        report.fail(f"the app's settings did not load: {describe(exc)}")
        return False, None

    try:
        with engine.connect() as conn:
            version = conn.execute(text("SHOW server_version")).scalar()
            dbapi = conn.connection.dbapi_connection
            client_ssl = bool(getattr(getattr(dbapi, "pgconn", None), "ssl_in_use", False))
            try:
                row = conn.execute(
                    text("SELECT ssl, version FROM pg_stat_ssl WHERE pid = pg_backend_pid()")
                ).first()
            except Exception:  # pg_stat_ssl unreadable; not fatal
                conn.rollback()
                row = None
            has_version_table = (
                conn.execute(text("SELECT to_regclass('public.alembic_version')")).scalar()
                is not None
            )
            before = (
                conn.execute(text("SELECT version_num FROM alembic_version")).scalar()
                if has_version_table
                else None
            )
    except Exception as exc:
        report.fail(f"could not connect: {describe(exc)}", hint_for(exc))
        return False, None

    report.ok("connected")
    report.ok(f"PostgreSQL {version}")

    if client_ssl:
        report.ok("SSL on between this machine and Supabase")
    else:
        report.fail(
            "SSL is OFF between this machine and Supabase",
            "Keep ?sslmode=require at the end of the URL.",
        )

    if row is None:
        report.info("pg_stat_ssl: not readable for this session")
    elif row[0]:
        report.ok(f"pg_stat_ssl: SSL on ({row[1]})")
    else:
        report.info(
            "pg_stat_ssl: off",
            "This describes the pooler's own hop to Postgres, inside Supabase.\n"
            "The link from this machine, which carries the password, is the one\n"
            "reported above.",
        )

    if before:
        report.info(f"schema revision before upgrade: {before}")
    else:
        report.info("schema revision before upgrade: none (empty database)")
    return True, before


# ---------------------------------------------------------------------------
# 3. Migrate
# ---------------------------------------------------------------------------


def run_migrations(report: Report, before: str | None) -> str | None:
    """Returns the head revision if the upgrade and the drift check both pass."""
    report.section("Migrations (Alembic - its own log lines follow)")
    from alembic.config import Config
    from alembic.script import ScriptDirectory
    from alembic.util import AutogenerateDiffsDetected
    from sqlalchemy import text

    from alembic import command
    from app.database.session import engine

    cfg = Config(str(BACKEND / "alembic.ini"))
    head = ScriptDirectory.from_config(cfg).get_current_head()

    try:
        command.upgrade(cfg, "head")
    except Exception as exc:
        report.fail(f"alembic upgrade head: {describe(exc)}", hint_for(exc))
        return None

    with engine.connect() as conn:
        after = conn.execute(text("SELECT version_num FROM alembic_version")).scalar()

    if after != head:
        report.fail(f"alembic upgrade head finished at {after}, expected {head}")
        return None
    if before == after:
        report.ok(f"alembic upgrade head: already at {head}, nothing to do")
    elif before is None:
        report.ok(f"alembic upgrade head: built the schema -> {head}")
    else:
        report.ok(f"alembic upgrade head: {before} -> {head}")

    try:
        command.check(cfg)
    except AutogenerateDiffsDetected as exc:
        report.fail(
            "alembic check: the database and the models disagree",
            describe(exc),
        )
        return None
    except Exception as exc:
        report.fail(f"alembic check: {describe(exc)}")
        return None
    report.ok("alembic check: no drift between the models and the migrations")
    return head


# ---------------------------------------------------------------------------
# 4. The app's own database layer, in production mode
# ---------------------------------------------------------------------------


def check_app_layer(report: Report, head: str) -> None:
    report.section("App database layer (ENVIRONMENT=production)")
    from sqlalchemy import inspect, text

    from app.database.session import engine, init_db
    from app.models.entities import Base

    try:
        init_db()
    except Exception as exc:
        report.fail(f"init_db(): {describe(exc)}")
        return
    report.ok("init_db() passed - the service will boot against this database")

    with engine.connect() as conn:
        revision = conn.execute(text("SELECT version_num FROM alembic_version")).scalar()
    if revision == head:
        report.ok(f"alembic_version: {revision}")
    else:
        report.fail(f"alembic_version is {revision}, expected {head}")

    tables = sorted(inspect(engine).get_table_names())
    expected = set(Base.metadata.tables) | {"alembic_version"}
    missing = sorted(expected - set(tables))
    if missing:
        report.fail(f"missing tables: {', '.join(missing)}")
    else:
        report.ok(f"tables ({len(tables)}): {', '.join(tables)}")


def check_public_roles(report: Report) -> None:
    report.section("Supabase public API roles")
    from sqlalchemy import text

    from app.database.session import engine

    with engine.connect() as conn:
        anon = conn.execute(text("SELECT 1 FROM pg_roles WHERE rolname = 'anon'")).first()
        if anon is None:
            report.info("no 'anon' role on this server - check skipped")
            return
        can_read = conn.execute(
            text("SELECT has_table_privilege('anon', 'public.competitors', 'SELECT')")
        ).scalar()

    if can_read:
        report.warn("the public 'anon' role CAN read public.competitors", ANON_FIX)
    else:
        report.ok("the public 'anon' role cannot read public.competitors")


# ---------------------------------------------------------------------------


def finish(report: Report) -> int:
    print(flush=True)
    if report.failed:
        print(
            f"Result: FAIL - {report.failed} failed, {report.warned} warning(s).\n"
            "Fix the first FAIL above and run the script again.",
            flush=True,
        )
        return 1
    print(
        f"Result: PASS - 0 failed, {report.warned} warning(s).\n"
        "The connection string you entered is ready to use as DATABASE_URL on Render.",
        flush=True,
    )
    return 0


def main() -> int:
    harden_console()
    report = Report()
    print("RivalRadar - Supabase database check", flush=True)

    got = read_url()
    if got is None:
        report.fail("no connection string entered")
        return finish(report)
    raw, source = got

    target = check_url(clean(raw), source, report)
    if target is None:
        return finish(report)

    prepare_process(target.url)

    connected, before = check_connection(report)
    if not connected:
        return finish(report)

    head = run_migrations(report, before)
    if head is not None:
        check_app_layer(report, head)
        check_public_roles(report)

    with contextlib.suppress(Exception):
        from app.database.session import engine

        engine.dispose()
    return finish(report)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\nCancelled.", flush=True)
        sys.exit(1)
    except Exception as exc:  # last resort: still no traceback, still redacted
        print(f"\n  FAIL  unexpected error: {describe(exc)}", flush=True)
        sys.exit(1)
