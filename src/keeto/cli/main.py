"""Keeto CLI — `keeto` command entry point (issues #91–#99)."""

from __future__ import annotations

import asyncio
import json
import sys
from enum import StrEnum
from pathlib import Path
from typing import Annotated

try:
    import typer
    from rich import box
    from rich.console import Console
    from rich.table import Table
except ImportError as exc:
    raise ImportError("CLI requires typer and rich. Install with: pip install keeto[dev]") from exc

import contextlib
from datetime import UTC

from keeto._version import __version__

app = typer.Typer(
    name="keeto",
    help="Keeto — AI observability for Python.",
    no_args_is_help=True,
    rich_markup_mode="rich",
)

console = Console()

# ---------------------------------------------------------------------------
# Shared types / helpers
# ---------------------------------------------------------------------------

_DEFAULT_DB_PATHS = [Path("keeto.db"), Path.home() / ".keeto" / "keeto.db"]

DbOption = Annotated[
    Path | None,
    typer.Option(
        "--db",
        help="Path to keeto SQLite database (default: ./keeto.db or ~/.keeto/keeto.db).",
        envvar="KEETO_DB",
        show_default=False,
    ),
]


def _resolve_db(db: Path | None) -> Path:
    if db is not None:
        if not db.exists():
            console.print(f"[red]Database not found:[/red] {db}")
            raise typer.Exit(1)
        return db
    for candidate in _DEFAULT_DB_PATHS:
        if candidate.exists():
            return candidate
    console.print(
        "[red]No keeto database found.[/red] "
        "Point to one with [bold]--db PATH[/bold] or [bold]KEETO_DB[/bold], "
        "or configure SQLite storage: [bold]Monitor(storage=SQLiteStorage('keeto.db'))[/bold]"
    )
    raise typer.Exit(1)


def _open_storage(db: Path):  # type: ignore[return]
    try:
        from keeto.storage.sqlite import SQLiteStorage
    except ImportError:
        console.print(
            "[red]SQLite storage requires aiosqlite.[/red] Install with: [bold]pip install keeto[sqlite][/bold]"
        )
        raise typer.Exit(1) from None
    return SQLiteStorage(str(db))


# ---------------------------------------------------------------------------
# #91 — CLI skeleton: version + shell completion
# ---------------------------------------------------------------------------


@app.command()
def version() -> None:
    """Show the Keeto version."""
    console.print(f"keeto [bold]{__version__}[/bold]")


# Typer exposes --install-completion / --show-completion automatically when
# the app is created; no extra work needed for shell completion.


# ---------------------------------------------------------------------------
# #92 — `keeto traces` — list recent traces
# ---------------------------------------------------------------------------


class OutputFormat(StrEnum):
    table = "table"
    json = "json"


@app.command()
def traces(
    db: DbOption = None,
    limit: Annotated[int, typer.Option("--limit", "-n", help="Max traces to show.")] = 20,
    provider: Annotated[str | None, typer.Option("--provider", help="Filter by provider.")] = None,
    model: Annotated[str | None, typer.Option("--model", help="Filter by model name (substring).")] = None,
    errors_only: Annotated[bool, typer.Option("--errors", help="Show only failed traces.")] = False,
    format: Annotated[OutputFormat, typer.Option("--format", "-f", help="Output format.")] = OutputFormat.table,
) -> None:
    """List recent captured traces from the keeto database."""
    resolved = _resolve_db(db)
    storage = _open_storage(resolved)

    all_traces = asyncio.run(storage.list_traces(limit=limit * 10))  # over-fetch for client-side filter

    # client-side filtering (SQLite backend doesn't expose provider/model WHERE clauses yet)
    filtered = []
    for t in all_traces:
        if provider and (t.provider or "").lower() != provider.lower():
            continue
        if model and model.lower() not in (t.model or "").lower():
            continue
        if errors_only and not t.has_error:
            continue
        filtered.append(t)
        if len(filtered) >= limit:
            break

    if format == OutputFormat.json:
        data = [
            {
                "trace_id": t.trace_id,
                "provider": t.provider,
                "model": t.model,
                "start_time": t.start_time.isoformat(),
                "latency_ms": round(t.latency_ms, 1) if t.latency_ms else None,
                "input_tokens": t.total_input_tokens,
                "output_tokens": t.total_output_tokens,
                "cost_usd": round(t.total_cost_usd, 6),
                "has_error": t.has_error,
            }
            for t in filtered
        ]
        sys.stdout.write(json.dumps(data, indent=2, default=str))
        sys.stdout.write("\n")
        return

    if not filtered:
        console.print("[yellow]No traces found.[/yellow]")
        return

    table = Table(
        box=box.SIMPLE_HEAD,
        show_footer=False,
        highlight=True,
        header_style="bold",
    )
    table.add_column("Trace ID", style="dim", no_wrap=True, max_width=12)
    table.add_column("Provider", no_wrap=True)
    table.add_column("Model", no_wrap=True)
    table.add_column("Latency", justify="right")
    table.add_column("In tok", justify="right")
    table.add_column("Out tok", justify="right")
    table.add_column("Cost USD", justify="right")
    table.add_column("Status", justify="center")

    for t in filtered:
        latency = f"{t.latency_ms:,.0f}ms" if t.latency_ms else "—"
        cost = f"${t.total_cost_usd:.4f}" if t.total_cost_usd else "—"
        status = "[red]ERROR[/red]" if t.has_error else "[green]OK[/green]"
        table.add_row(
            t.trace_id[:12],
            t.provider or "—",
            t.model or "—",
            latency,
            str(t.total_input_tokens) if t.total_input_tokens else "—",
            str(t.total_output_tokens) if t.total_output_tokens else "—",
            cost,
            status,
        )

    console.print(table)
    console.print(f"[dim]{len(filtered)} trace(s) from {resolved}[/dim]")


# ---------------------------------------------------------------------------
# #93 — `keeto dashboard` — launch TUI or web dashboard
# ---------------------------------------------------------------------------


class DashboardMode(StrEnum):
    tui = "tui"
    web = "web"
    rich = "rich"


@app.command()
def dashboard(
    db: DbOption = None,
    mode: Annotated[
        DashboardMode,
        typer.Option("--mode", "-m", help="Dashboard mode: tui, web, or rich."),
    ] = DashboardMode.tui,
    port: Annotated[int, typer.Option("--port", help="Port for web dashboard.")] = 7842,
) -> None:
    """Launch the Keeto dashboard (TUI, web, or rich summary)."""
    resolved = _resolve_db(db)
    storage = _open_storage(resolved)

    if mode == DashboardMode.rich:
        all_traces = asyncio.run(storage.list_traces(limit=200))
        from keeto.dashboard.rich_summary import render

        render(all_traces, console=console)
        return

    if mode == DashboardMode.tui:
        try:
            from keeto.dashboard.tui.app import KeetoApp
        except ImportError:
            console.print("[red]TUI requires textual.[/red] Install with: [bold]pip install keeto[tui][/bold]")
            raise typer.Exit(1) from None
        KeetoApp(storage=storage).run()
        return

    if mode == DashboardMode.web:
        try:
            from keeto.dashboard.web.server import start_web_dashboard
        except ImportError:
            console.print(
                "[red]Web dashboard requires fastapi.[/red] Install with: [bold]pip install keeto[web][/bold]"
            )
            raise typer.Exit(1) from None
        console.print(f"[bold green]Starting web dashboard on http://localhost:{port}[/bold green]")
        start_web_dashboard(storage, port=port, block=True)


# ---------------------------------------------------------------------------
# #94 — `keeto replay <trace-id>` — re-send a captured trace
# ---------------------------------------------------------------------------


@app.command()
def replay(
    trace_id: Annotated[str, typer.Argument(help="Trace ID (or prefix) to replay.")],
    db: DbOption = None,
    dry_run: Annotated[bool, typer.Option("--dry-run", help="Print request without sending.")] = False,
) -> None:
    """Replay a captured trace — re-sends the original LLM request."""
    resolved = _resolve_db(db)
    storage = _open_storage(resolved)

    # Support prefix matching: fetch recent traces and find by prefix
    trace = asyncio.run(storage.get_trace(trace_id))
    if trace is None:
        # Try prefix match
        all_traces = asyncio.run(storage.list_traces(limit=1000))
        matches = [t for t in all_traces if t.trace_id.startswith(trace_id)]
        if not matches:
            console.print(f"[red]Trace not found:[/red] {trace_id!r}")
            raise typer.Exit(1)
        if len(matches) > 1:
            console.print(f"[yellow]Ambiguous prefix — {len(matches)} matches:[/yellow]")
            for m in matches[:5]:
                console.print(f"  {m.trace_id}")
            raise typer.Exit(1)
        trace = matches[0]

    root = trace.root_span
    if root is None:
        console.print("[red]Trace has no root span — cannot replay.[/red]")
        raise typer.Exit(1)

    messages = root.attributes.get("llm.messages")
    if messages is None:
        console.print(
            "[red]No messages stored on this trace.[/red] "
            "Enable [bold]store_prompts=True[/bold] on the Monitor to capture messages for replay."
        )
        raise typer.Exit(1)

    console.print(f"[bold]Replaying trace:[/bold] {trace.trace_id}")
    console.print(f"  Provider : {root.provider or '—'}")
    console.print(f"  Model    : {root.model or '—'}")
    console.print(f"  Messages : {len(messages)} message(s)")

    if dry_run:
        console.print("\n[bold]Dry-run — request payload:[/bold]")
        console.print(json.dumps({"model": root.model, "messages": messages}, indent=2, default=str))
        return

    try:
        result = trace.replay()
        console.print("[green]Replay complete.[/green]")
        if hasattr(result, "choices"):
            content = result.choices[0].message.content if result.choices else ""
            console.print(f"\n[dim]Response:[/dim] {content[:200]}")
        elif hasattr(result, "content"):
            text = result.content[0].text if result.content else ""
            console.print(f"\n[dim]Response:[/dim] {text[:200]}")
    except Exception as exc:
        console.print(f"[red]Replay failed:[/red] {exc}")
        raise typer.Exit(1) from exc


# ---------------------------------------------------------------------------
# #95 — `keeto export` — export traces
# ---------------------------------------------------------------------------


class ExportFormat(StrEnum):
    json = "json"
    csv = "csv"
    otel = "otel"


@app.command()
def export(
    db: DbOption = None,
    format: Annotated[
        ExportFormat | None,
        typer.Option("--format", "-f", help="Export format: json, csv, or otel."),
    ] = None,
    output: Annotated[
        Path | None,
        typer.Option("--output", "-o", help="Output file path (stdout if omitted)."),
    ] = None,
    since: Annotated[str | None, typer.Option("--since", help="Start time filter (ISO-8601).")] = None,
    until: Annotated[str | None, typer.Option("--until", help="End time filter (ISO-8601).")] = None,
    limit: Annotated[int, typer.Option("--limit", "-n", help="Max traces to export.")] = 10_000,
    endpoint: Annotated[
        str | None,
        typer.Option("--endpoint", help="OTLP endpoint URL (for --format otel)."),
    ] = None,
) -> None:
    """Export traces to JSON, CSV, or OpenTelemetry OTLP."""
    from datetime import datetime

    def _parse_dt(v: str | None) -> datetime | None:
        if v is None:
            return None
        dt = datetime.fromisoformat(v)
        return dt if dt.tzinfo else dt.replace(tzinfo=UTC)

    resolved = _resolve_db(db)
    storage = _open_storage(resolved)

    # Infer format from output extension if not given
    effective_format = format
    if effective_format is None and output is not None:
        ext = output.suffix.lstrip(".").lower()
        with contextlib.suppress(ValueError):
            effective_format = ExportFormat(ext)
    if effective_format is None:
        effective_format = ExportFormat.json

    since_dt = _parse_dt(since)
    until_dt = _parse_dt(until)
    all_traces = asyncio.run(storage.list_traces(limit=limit, since=since_dt, until=until_dt))

    out_path = str(output) if output else None

    if effective_format == ExportFormat.json:
        from keeto.exporters.json import export_json

        export_json(all_traces, out_path)
    elif effective_format == ExportFormat.csv:
        from keeto.exporters.csv import export_csv

        export_csv(all_traces, out_path)
    elif effective_format == ExportFormat.otel:
        from keeto.exporters.otel import export_otel

        kwargs: dict = {}
        if endpoint:
            kwargs["endpoint"] = endpoint
        export_otel(all_traces, **kwargs)
    else:
        console.print(f"[red]Unknown format:[/red] {effective_format}")
        raise typer.Exit(1)

    if output:
        console.print(f"[green]Exported {len(all_traces)} trace(s)[/green] → {output} ({effective_format.value})")


# ---------------------------------------------------------------------------
# #96 — `keeto analyze` — recommendations report
# ---------------------------------------------------------------------------


@app.command()
def analyze(
    db: DbOption = None,
    json_output: Annotated[bool, typer.Option("--json", help="Output as JSON.")] = False,
) -> None:
    """Print a recommendations report from captured traces."""
    resolved = _resolve_db(db)
    storage = _open_storage(resolved)
    all_traces = asyncio.run(storage.list_traces(limit=10_000))

    from keeto.analyzers.recommendations import RecommendationsEngine

    report = RecommendationsEngine().analyze(all_traces)

    if json_output:
        import dataclasses

        data = [dataclasses.asdict(r) for r in report.recommendations]
        sys.stdout.write(json.dumps(data, indent=2, default=str))
        sys.stdout.write("\n")
        return

    if not report.recommendations:
        console.print("[green]No recommendations — everything looks good.[/green]")
        return

    _sev_style = {"error": "bold red", "warning": "yellow", "info": "cyan"}
    _sev_icon = {"error": "✗", "warning": "!", "info": "i"}
    _sev_order = {"error": 0, "warning": 1, "info": 2}

    for r in sorted(report.recommendations, key=lambda x: _sev_order.get(x.severity, 3)):
        style = _sev_style.get(r.severity, "")
        icon = _sev_icon.get(r.severity, "-")
        console.print(f"[{style}][{icon}][/{style}] [{style}]{r.rule}[/{style}]: {r.message}")

    console.print(f"\n[dim]{len(report.recommendations)} recommendation(s) from {resolved}[/dim]")


# ---------------------------------------------------------------------------
# #97 — `keeto config [get|set|list]` — manage ~/.keeto/config.toml
# ---------------------------------------------------------------------------

_CONFIG_PATH = Path.home() / ".keeto" / "config.toml"

config_app = typer.Typer(name="config", help="Manage ~/.keeto/config.toml settings.", no_args_is_help=True)
app.add_typer(config_app)


def _load_config() -> dict:
    if not _CONFIG_PATH.exists():
        return {}
    import tomllib

    return tomllib.loads(_CONFIG_PATH.read_text(encoding="utf-8"))


def _save_config(cfg: dict) -> None:
    _CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    lines: list[str] = []
    for k, v in cfg.items():
        if isinstance(v, str):
            lines.append(f'{k} = "{v}"')
        elif isinstance(v, bool):
            lines.append(f"{k} = {str(v).lower()}")
        elif isinstance(v, (int, float)):
            lines.append(f"{k} = {v}")
        else:
            lines.append(f'{k} = "{v}"')
    _CONFIG_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")


@config_app.command("list")
def config_list() -> None:
    """List all config keys and values."""
    cfg = _load_config()
    if not cfg:
        console.print(f"[dim]No config at {_CONFIG_PATH}[/dim]")
        return
    table = Table(box=box.SIMPLE_HEAD, show_header=True, header_style="bold")
    table.add_column("Key")
    table.add_column("Value")
    for k, v in sorted(cfg.items()):
        table.add_row(k, str(v))
    console.print(table)
    console.print(f"[dim]{_CONFIG_PATH}[/dim]")


@config_app.command("get")
def config_get(
    key: Annotated[str, typer.Argument(help="Config key to read.")],
) -> None:
    """Get a single config value."""
    cfg = _load_config()
    if key not in cfg:
        console.print(f"[yellow]{key}[/yellow] is not set.")
        raise typer.Exit(1)
    console.print(str(cfg[key]))


@config_app.command("set")
def config_set(
    key: Annotated[str, typer.Argument(help="Config key to set.")],
    value: Annotated[str, typer.Argument(help="Value to assign.")],
) -> None:
    """Set a config key to a value."""
    cfg = _load_config()
    cfg[key] = value
    _save_config(cfg)
    console.print(f"[green]Set[/green] {key} = {value!r}  ({_CONFIG_PATH})")


@config_app.command("unset")
def config_unset(
    key: Annotated[str, typer.Argument(help="Config key to remove.")],
) -> None:
    """Remove a config key."""
    cfg = _load_config()
    if key not in cfg:
        console.print(f"[yellow]{key}[/yellow] is not set — nothing to remove.")
        return
    del cfg[key]
    _save_config(cfg)
    console.print(f"[green]Removed[/green] {key}  ({_CONFIG_PATH})")


# ---------------------------------------------------------------------------
# #98 — `keeto doctor` — diagnose setup
# ---------------------------------------------------------------------------


@app.command()
def doctor(db: DbOption = None) -> None:
    """Diagnose your Keeto setup — checks deps, DB, plugins, and env vars."""
    import importlib
    import sys as _sys

    ok = "[bold green]✓[/bold green]"
    warn = "[bold yellow]![/bold yellow]"
    err = "[bold red]✗[/bold red]"

    console.print(f"\n[bold]keeto doctor[/bold]  (keeto {__version__})\n")

    # ---- Python version ----
    major, minor = _sys.version_info[:2]
    py_label = f"Python {major}.{minor}"
    if (major, minor) >= (3, 11):
        console.print(f"  {ok}  {py_label}")
    else:
        console.print(f"  {err}  {py_label}  [red](keeto requires >=3.11)[/red]")

    # ---- Core deps ----
    console.print()
    console.print("  [bold]Core dependencies[/bold]")
    for pkg in ("pydantic", "anyio", "httpx", "rich", "typer"):
        try:
            mod = importlib.import_module(pkg)
            ver = getattr(mod, "__version__", "?")
            console.print(f"  {ok}  {pkg} {ver}")
        except ImportError:
            console.print(f"  {err}  {pkg}  [red](missing — run: pip install keeto)[/red]")

    # ---- Optional extras ----
    console.print()
    console.print("  [bold]Optional extras[/bold]")
    optional = {
        "aiosqlite": "keeto[sqlite]",
        "textual": "keeto[tui]",
        "fastapi": "keeto[web]",
        "opentelemetry": "keeto[otel]",
        "asyncpg": "keeto[postgres]",
    }
    for pkg, extra in optional.items():
        try:
            mod = importlib.import_module(pkg)
            ver = getattr(mod, "__version__", "?")
            console.print(f"  {ok}  {pkg} {ver}")
        except ImportError:
            console.print(f"  {warn}  {pkg}  [dim](optional — pip install {extra})[/dim]")

    # ---- AI SDKs ----
    console.print()
    console.print("  [bold]AI SDK detection[/bold]")
    sdks = [
        "openai",
        "anthropic",
        "langchain",
        "llama_index",
        "litellm",
        "google.generativeai",
        "ollama",
        "pydantic_ai",
    ]
    found_any = False
    for sdk in sdks:
        try:
            mod = importlib.import_module(sdk)
            ver = getattr(mod, "__version__", "?")
            console.print(f"  {ok}  {sdk} {ver}")
            found_any = True
        except ImportError:
            pass
    if not found_any:
        console.print(f"  {warn}  No AI SDKs detected — install openai, anthropic, etc.")

    # ---- Database ----
    console.print()
    console.print("  [bold]Database[/bold]")
    db_path: Path | None = None
    if db is not None and db.exists():
        db_path = db
    else:
        for candidate in _DEFAULT_DB_PATHS:
            if candidate.exists():
                db_path = candidate
                break
    if db_path:
        size_kb = db_path.stat().st_size / 1024
        console.print(f"  {ok}  {db_path}  ({size_kb:.1f} KB)")
        try:
            from keeto.storage.sqlite import SQLiteStorage

            storage = SQLiteStorage(str(db_path))
            asyncio.run(storage.list_traces(limit=1))
            asyncio.run(storage.close())
            console.print(f"  {ok}  Database readable")
        except Exception as exc:
            console.print(f"  {err}  Database error: {exc}")
    else:
        console.print(
            f"  {warn}  No database found at ./keeto.db or ~/.keeto/keeto.db\n"
            f"         [dim]Use SQLiteStorage('keeto.db') in your app to persist traces.[/dim]"
        )

    # ---- Config file ----
    console.print()
    console.print("  [bold]Config[/bold]")
    if _CONFIG_PATH.exists():
        console.print(f"  {ok}  {_CONFIG_PATH}")
    else:
        console.print(f"  {warn}  No config at {_CONFIG_PATH}  [dim](run: keeto config set <key> <val>)[/dim]")

    # ---- Env vars ----
    console.print()
    console.print("  [bold]Environment variables[/bold]")
    import os

    env_vars = {
        "OPENAI_API_KEY": "OpenAI",
        "ANTHROPIC_API_KEY": "Anthropic",
        "GOOGLE_API_KEY": "Gemini",
        "KEETO_DB": "Keeto DB override",
    }
    for var, label in env_vars.items():
        val = os.environ.get(var)
        if val:
            masked = val[:4] + "…" if len(val) > 4 else "set"
            console.print(f"  {ok}  {var}={masked}  [dim]({label})[/dim]")
        else:
            icon = warn if "API_KEY" in var else "[dim]-[/dim]"
            console.print(f"  {icon}  {var}  [dim](not set)[/dim]")

    # ---- Plugin registry ----
    console.print()
    console.print("  [bold]Plugin registry[/bold]")
    try:
        import importlib.metadata as _meta

        eps = list(_meta.entry_points(group="keeto.plugins"))
        if eps:
            for ep in eps:
                console.print(f"  {ok}  {ep.name}  [dim]({ep.value})[/dim]")
        else:
            console.print(f"  {warn}  No plugins found in entry point group 'keeto.plugins'")
    except Exception as exc:
        console.print(f"  {err}  Plugin registry error: {exc}")

    console.print()


# ---------------------------------------------------------------------------
# #99 — `keeto compare <id1> <id2>` — side-by-side trace diff
# ---------------------------------------------------------------------------


def _resolve_trace(storage, trace_id: str):  # type: ignore[return]
    """Fetch a trace by full ID or prefix."""
    trace = asyncio.run(storage.get_trace(trace_id))
    if trace is not None:
        return trace
    all_traces = asyncio.run(storage.list_traces(limit=1000))
    matches = [t for t in all_traces if t.trace_id.startswith(trace_id)]
    if not matches:
        return None
    if len(matches) > 1:
        ids = ", ".join(t.trace_id for t in matches[:5])
        raise ValueError(f"Ambiguous prefix — matches: {ids}")
    return matches[0]


@app.command()
def compare(
    id1: Annotated[str, typer.Argument(help="First trace ID (or prefix).")],
    id2: Annotated[str, typer.Argument(help="Second trace ID (or prefix).")],
    db: DbOption = None,
    json_output: Annotated[bool, typer.Option("--json", help="Output as JSON.")] = False,
) -> None:
    """Side-by-side comparison of two traces."""
    resolved = _resolve_db(db)
    storage = _open_storage(resolved)

    try:
        trace_a = _resolve_trace(storage, id1)
        trace_b = _resolve_trace(storage, id2)
    except ValueError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1) from exc

    if trace_a is None:
        console.print(f"[red]Trace not found:[/red] {id1!r}")
        raise typer.Exit(1)
    if trace_b is None:
        console.print(f"[red]Trace not found:[/red] {id2!r}")
        raise typer.Exit(1)

    from keeto.analyzers.comparison import TraceComparison

    cmp = TraceComparison.from_traces(trace_a, trace_b)

    if json_output:
        import dataclasses

        sys.stdout.write(json.dumps(dataclasses.asdict(cmp), indent=2, default=str))
        sys.stdout.write("\n")
        return

    # Rich table rendering
    def _fmt_lat(ms: float | None) -> str:
        return f"{ms:,.0f}ms" if ms is not None else "—"

    def _delta_style(val: float, unit: str = "") -> str:
        if val > 0:
            return f"[red]+{val:.0f}{unit}[/red]"
        if val < 0:
            return f"[green]{val:.0f}{unit}[/green]"
        return f"0{unit}"

    table = Table(box=box.SIMPLE_HEAD, show_header=True, header_style="bold", title="Trace Comparison")
    table.add_column("Metric", style="bold")
    table.add_column(f"A  ({cmp.trace_id_a[:12]})", justify="right")
    table.add_column(f"B  ({cmp.trace_id_b[:12]})", justify="right")
    table.add_column("Δ  (B − A)", justify="right")

    table.add_row("Model", cmp.model_a or "—", cmp.model_b or "—", "")

    lat_delta = ""
    if cmp.latency_delta_ms is not None:
        lat_delta = _delta_style(cmp.latency_delta_ms, "ms")
    table.add_row("Latency", _fmt_lat(cmp.latency_a_ms), _fmt_lat(cmp.latency_b_ms), lat_delta)

    cost_delta = _delta_style(cmp.cost_delta_usd * 1_000_000, "µ$") if cmp.cost_delta_usd != 0 else "—"
    table.add_row(
        "Cost (USD)",
        f"${cmp.cost_a_usd:.6f}",
        f"${cmp.cost_b_usd:.6f}",
        cost_delta,
    )

    has_in = cmp.input_tokens_a or cmp.input_tokens_b
    in_delta = _delta_style(cmp.input_tokens_b - cmp.input_tokens_a, " tok") if has_in else "—"
    table.add_row("Input tokens", str(cmp.input_tokens_a), str(cmp.input_tokens_b), in_delta)

    has_out = cmp.output_tokens_a or cmp.output_tokens_b
    out_delta = _delta_style(cmp.output_tokens_b - cmp.output_tokens_a, " tok") if has_out else "—"
    table.add_row("Output tokens", str(cmp.output_tokens_a), str(cmp.output_tokens_b), out_delta)

    console.print(table)
    console.print(f"[dim]from {resolved}[/dim]")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    app()
