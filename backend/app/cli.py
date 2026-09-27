"""RivalRadar developer CLI.

Installed as ``rivalradar`` (see pyproject.toml), or run directly::

    python -m app.cli --help

Commands::

    rivalradar init                     create the database
    rivalradar reset                    delete all tracked data
    rivalradar llm-check                verify the OpenRouter key and model work
    rivalradar add-competitor           add a real competitor to track
    rivalradar list                     list tracked competitors
    rivalradar scan                     scan every active competitor
    rivalradar scan --competitor 1      scan one competitor
    rivalradar digest                   generate and print the weekly digest
    rivalradar wayback --url <url>      run a Wayback evaluation
    rivalradar evaluate                 run the full evaluation suite
    rivalradar seed                     load FICTIONAL demo data (DEMO_MODE=true only)
    rivalradar serve                    start the API server
"""

from __future__ import annotations

import json
from typing import Annotated

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from app.config.logging import configure_console_encoding, configure_logging
from app.config.settings import settings

# Must run before Rich inspects the stream encoding.
configure_console_encoding()

app = typer.Typer(
    name="rivalradar",
    help="AI competitor tracking agent.",
    add_completion=False,
    no_args_is_help=True,
)
console = Console()


def _funnel_table(stats: dict, title: str = "Change funnel") -> Table:
    """Render the noise-reduction funnel as a table."""
    table = Table(title=title, show_header=False, title_justify="left")
    table.add_column("Metric", style="bold")
    table.add_column("Value", justify="right")
    table.add_row("Raw changes detected", str(stats.get("raw_changes", 0)))
    table.add_row("Noise / irrelevant changes", str(stats.get("noise_changes", 0)))
    table.add_row("Meaningful changes", str(stats.get("meaningful_changes", 0)))
    table.add_row("High-priority changes", str(stats.get("high_impact_changes", 0)))
    reduction = stats.get("noise_reduction", 0)
    table.add_row("[green]Noise reduction[/green]", f"[green]{reduction}%[/green]")
    return table


@app.callback()
def main(verbose: bool = typer.Option(False, "--verbose", "-v", help="verbose logging")) -> None:
    """Configure logging for every command."""
    configure_logging("DEBUG" if verbose else "WARNING")


@app.command("init")
def init_command() -> None:
    """Create the database schema."""
    from sqlalchemy.engine import make_url

    from app.database.session import init_db

    settings.ensure_directories()
    init_db()
    # Never print the URL itself: a PostgreSQL URL carries the username and
    # password. A SQLite URL holds only a local file path, which is worth showing.
    if settings.database_backend == "sqlite":
        location = make_url(settings.database_url).database or ":memory:"
        console.print(f"[green]Database ready[/green] at {location}")
    else:
        console.print(f"[green]Database ready[/green] ({settings.database_backend})")


@app.command("reset")
def reset_command(
    yes: Annotated[bool, typer.Option("--yes", "-y", help="skip the confirmation prompt")] = False,
) -> None:
    """Delete every competitor, snapshot, change and intelligence record."""
    from app.database.seed import clear_demo_data
    from app.database.session import init_db, session_scope

    if not yes:
        confirmed = typer.confirm(
            "This permanently deletes all tracked competitors and their data. Continue?"
        )
        if not confirmed:
            console.print("Cancelled.")
            raise typer.Exit(code=1)

    init_db()
    with session_scope() as session:
        clear_demo_data(session)
    console.print("[green]Database cleared.[/green] No competitors are tracked.")


@app.command("llm-check")
def llm_check_command() -> None:
    """Make one real request to the configured LLM and report the result.

    Proves whether AI analysis will actually work before you run a scan.
    """
    from app.llm.factory import describe_analyst, reset_provider
    from app.llm.openrouter_provider import OpenRouterLLMService

    reset_provider()
    analyst = describe_analyst()

    console.print(f"Configured provider : [bold]{settings.llm_provider}[/bold]")
    console.print(f"Active analyst      : [bold]{analyst['provider']}[/bold]")
    console.print(f"Model               : [bold]{analyst['model']}[/bold]")

    if not analyst["is_llm"]:
        console.print()
        console.print(
            "[yellow]No LLM is active.[/yellow] Analysis will be deterministic "
            "(rule-based) and labelled as such."
        )
        console.print("Set OPENROUTER_API_KEY in backend/.env to enable AI analysis.")
        raise typer.Exit(code=1)

    with console.status("Calling the model..."):
        result = OpenRouterLLMService().ping()

    console.print()
    if result.get("ok"):
        console.print(
            f"[green]OK[/green] - live response from [bold]{result.get('model')}[/bold] "
            f"({result.get('tokens_used', 0)} tokens)."
        )
        console.print(f"Response: {result.get('response')}")
    else:
        console.print(f"[red]FAILED[/red] - {result.get('reason')}")
        console.print(
            "Scans will still run; analysis falls back to deterministic and is "
            "labelled 'AI analysis temporarily unavailable'."
        )
        raise typer.Exit(code=1)


@app.command("seed")
def seed_command(
    reset: Annotated[bool, typer.Option(help="delete existing data first")] = True,
    use_llm: Annotated[bool, typer.Option("--llm/--no-llm", help="run LLM analysis")] = True,
    force: Annotated[bool, typer.Option("--force", help="seed even when DEMO_MODE=false")] = False,
) -> None:
    """Load FICTIONAL demo competitors. Requires DEMO_MODE=true.

    Demo data is fictional and must never be mistaken for real competitive
    intelligence, so seeding is refused unless demo mode is explicitly on.
    """
    from app.database.seed import run_seed

    if not settings.demo_mode and not force:
        console.print("[yellow]Refusing to seed fictional data.[/yellow]")
        console.print()
        console.print(
            "RivalRadar is configured for real competitor tracking (DEMO_MODE=false)."
        )
        console.print("To add a real competitor:")
        console.print(
            "  [bold]rivalradar add-competitor --name Acme "
            "--url https://acme.com/pricing[/bold]"
        )
        console.print()
        console.print(
            "If you really want fictional sample data, set DEMO_MODE=true in "
            "backend/.env, or pass --force."
        )
        raise typer.Exit(code=1)

    console.print("[yellow]Loading FICTIONAL demo data (not real companies).[/yellow]")
    with console.status("Seeding demo data and running the pipeline..."):
        stats = run_seed(reset=reset, llm_enabled=use_llm)
    console.print(_funnel_table(stats.to_dict(), "Demo seeding funnel (measured)"))


@app.command("add-competitor")
def add_competitor_command(
    name: Annotated[str, typer.Option(prompt=True, help="competitor name")],
    url: Annotated[str, typer.Option(prompt="Website URL", help="website URL")],
    track: Annotated[list[str] | None, typer.Option("--track", help="extra page to track")] = None,
    frequency: Annotated[str, typer.Option(help="hourly|daily|weekly|manual")] = "daily",
) -> None:
    """Add a competitor and optionally extra pages to track."""
    from app.database.session import init_db, session_scope
    from app.models.entities import TrackingFrequency
    from app.schemas.api import CompetitorCreate, TrackedURLCreate
    from app.services.competitors import DuplicateCompetitorError, create_competitor

    init_db()
    try:
        payload = CompetitorCreate(
            name=name,
            website_url=url,
            tracking_frequency=TrackingFrequency(frequency),
            tracked_urls=[TrackedURLCreate(url=u) for u in (track or [])],
        )
    except ValueError as exc:
        console.print(f"[red]Invalid input:[/red] {exc}")
        raise typer.Exit(code=1) from exc

    try:
        with session_scope() as session:
            competitor = create_competitor(session, payload)
            console.print(
                f"[green]Added[/green] {competitor.name} (id={competitor.id}) "
                f"with {len(competitor.tracked_urls)} tracked page(s)"
            )
            console.print(
                f"Run [bold]rivalradar scan --competitor {competitor.id}[/bold] "
                "to capture the baseline snapshot."
            )
    except DuplicateCompetitorError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from exc


@app.command("list")
def list_command() -> None:
    """List tracked competitors."""
    from app.database.session import init_db, session_scope
    from app.services.competitors import competitor_summary, list_competitors

    init_db()
    with session_scope() as session:
        competitors = list_competitors(session)
        if not competitors:
            console.print("[yellow]No competitors tracked yet.[/yellow]")
            console.print(
                "Add one: [bold]rivalradar add-competitor --name Acme "
                "--url https://acme.com/pricing[/bold]"
            )
            return

        table = Table(title="Tracked competitors")
        for column in ("ID", "Name", "Website", "Freq", "URLs", "Active", "Changes/wk", "High"):
            table.add_column(column)

        for competitor in competitors:
            summary = competitor_summary(session, competitor)
            table.add_row(
                str(competitor.id),
                competitor.name,
                competitor.website_url[:44],
                competitor.tracking_frequency,
                str(summary["tracked_url_count"]),
                "yes" if competitor.active else "no",
                str(summary["changes_this_week"]),
                str(summary["high_impact_this_week"]),
            )
        console.print(table)


@app.command("scan")
def scan_command(
    competitor: Annotated[
        int | None, typer.Option("--competitor", "-c", help="competitor id")
    ] = None,
    use_llm: Annotated[bool, typer.Option("--llm/--no-llm", help="run LLM analysis")] = True,
) -> None:
    """Scan one competitor, or every active competitor."""
    from app.database.session import init_db, session_scope
    from app.diff.types import DiffStats
    from app.services.competitors import NotFoundError, get_competitor
    from app.services.scan import scan_all, scan_competitor

    init_db()
    with session_scope() as session:
        if competitor is not None:
            try:
                record = get_competitor(session, competitor)
            except NotFoundError as exc:
                console.print(f"[red]{exc}[/red]")
                raise typer.Exit(code=1) from exc
            with console.status(f"Scanning {record.name}..."):
                outcomes = [scan_competitor(session, record, llm_enabled=use_llm)]
        else:
            with console.status("Scanning all active competitors..."):
                outcomes = scan_all(session, llm_enabled=use_llm)

    if not outcomes:
        console.print("[yellow]No active competitors to scan.[/yellow]")
        console.print(
            "Add one: [bold]rivalradar add-competitor --name Acme "
            "--url https://acme.com/pricing[/bold]"
        )
        return

    total = DiffStats()
    table = Table(title="Scan results")
    for column in ("Competitor", "Status", "URLs", "Raw", "Noise", "Meaningful", "High"):
        table.add_column(column)

    for outcome in outcomes:
        total = total.merge(outcome.stats)
        table.add_row(
            outcome.competitor_name,
            outcome.status,
            f"{outcome.urls_scanned}/{outcome.urls_scanned + outcome.urls_failed}",
            str(outcome.stats.raw_changes),
            str(outcome.stats.noise_changes),
            str(outcome.stats.meaningful_changes),
            str(outcome.stats.high_impact_changes),
        )
        for result in outcome.results:
            if result.status in {"failed", "unchanged", "baseline"}:
                console.print(f"  [dim]{result.url}: {result.status} - {result.message}[/dim]")

    console.print(table)
    console.print(_funnel_table(total.to_dict(), "Total funnel for this scan"))


@app.command("digest")
def digest_command(
    days: Annotated[int, typer.Option(help="period length in days")] = 7,
    save: Annotated[bool, typer.Option(help="store the digest in the database")] = True,
) -> None:
    """Generate and print a weekly competitive-intelligence digest."""
    from app.database.session import init_db, session_scope
    from app.intelligence.digest import generate_digest

    init_db()
    with console.status("Generating digest..."), session_scope() as session:
        digest = generate_digest(session, days=days, persist=save)
        content = digest.content

    console.print(Panel(content, title="Weekly digest", expand=False))


@app.command("wayback")
def wayback_command(
    url: Annotated[list[str] | None, typer.Option("--url", help="URL to evaluate")] = None,
    from_date: Annotated[str | None, typer.Option("--from", help="YYYY-MM-DD")] = None,
    to_date: Annotated[str | None, typer.Option("--to", help="YYYY-MM-DD")] = None,
    save: Annotated[bool, typer.Option(help="write a report to data/reports/")] = True,
) -> None:
    """Benchmark the diff pipeline against Internet Archive snapshots."""
    from app.evaluation.wayback import main as wayback_main

    argv: list[str] = []
    for value in url or []:
        argv.extend(["--url", value])
    if from_date:
        argv.extend(["--from", from_date])
    if to_date:
        argv.extend(["--to", to_date])
    if not save:
        argv.append("--no-save")

    raise typer.Exit(code=wayback_main(argv))


@app.command("evaluate")
def evaluate_command(
    url: Annotated[
        list[str] | None, typer.Option("--url", help="override the default URL set")
    ] = None,
    from_date: Annotated[str | None, typer.Option("--from", help="YYYY-MM-DD")] = None,
    to_date: Annotated[str | None, typer.Option("--to", help="YYYY-MM-DD")] = None,
    as_json: Annotated[bool, typer.Option("--json", help="print JSON")] = False,
) -> None:
    """Run the full evaluation suite and print citable metrics."""
    from app.evaluation.suite import run_evaluation_suite

    with console.status("Running evaluation suite (this makes live Archive requests)..."):
        report = run_evaluation_suite(urls=url, from_date=from_date, to_date=to_date)

    if as_json:
        console.print_json(json.dumps(report.to_dict()))
        return

    stats = report.stats
    console.print()
    console.print("[bold]RivalRadar Evaluation[/bold]")
    console.print("=" * 21)
    console.print()
    console.print(f"Pages evaluated: {len(report.successful_pages)}")
    console.print()
    console.print(f"Raw changes:        {stats.raw_changes}")
    console.print(f"Noise changes:      {stats.noise_changes}")
    console.print(f"Meaningful changes: {stats.meaningful_changes}")
    console.print()
    console.print(f"[green]Noise reduction:    {stats.noise_reduction}%[/green]")
    console.print()
    console.print(f"High-impact changes: {stats.high_impact_changes}")

    if report.categories:
        console.print()
        console.print("[bold]Detection categories[/bold]")
        for category, count in report.categories.items():
            console.print(f"  {category.capitalize():<16}{count}")

    failed = [page for page in report.pages if page.status != "completed"]
    if failed:
        console.print()
        console.print(f"[yellow]{len(failed)} page(s) could not be evaluated:[/yellow]")
        for page in failed:
            console.print(f"  [dim]{page.url}: {page.error}[/dim]")


@app.command("serve")
def serve_command(
    host: str = "127.0.0.1",
    port: int = 8000,
    reload: Annotated[bool, typer.Option(help="auto-reload on code changes")] = False,
) -> None:
    """Start the FastAPI server."""
    import uvicorn

    console.print(f"[green]Starting RivalRadar API[/green] at http://{host}:{port}/docs")
    uvicorn.run("app.main:app", host=host, port=port, reload=reload)


@app.command("graph")
def graph_command() -> None:
    """Print the LangGraph pipeline as a Mermaid diagram."""
    from app.agents.graph import render_mermaid

    diagram = render_mermaid()
    console.print(diagram or "[yellow]Could not render the graph diagram.[/yellow]")


if __name__ == "__main__":
    app()
