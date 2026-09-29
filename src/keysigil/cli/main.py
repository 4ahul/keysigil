from __future__ import annotations

import asyncio
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from keysigil import __version__

app = typer.Typer(
    name="keysigil",
    help="[bold green]KeyForge[/bold green] — API key management with LLM token budgets.",
    rich_markup_mode="rich",
    no_args_is_help=True,
    add_completion=False,
)
console = Console()

_DB_OPTION = typer.Option("sqlite:///keyforge.db", "--db", help="Database URL")


def _version_callback(value: bool) -> None:
    if value:
        console.print(f"keysigil {__version__}")
        raise typer.Exit()


@app.callback()
def main(
    version: bool = typer.Option(
        False, "--version", "-V", callback=_version_callback, is_eager=True, help="Show version"
    ),
) -> None:
    pass


def _get_kf(db: str) -> object:
    from keysigil.core.engine import KeyForge
    return KeyForge(db)


@app.command()
def init(db: str = _DB_OPTION) -> None:
    """Initialize the database (create tables)."""
    from keysigil.core.engine import KeyForge
    kf = KeyForge(db)
    asyncio.run(kf.setup())
    console.print(f"[green]✓[/green] Database ready: {db}")


@app.command()
def create(
    name: str = typer.Option(..., "--name", "-n", help="Key name"),
    prefix: Optional[str] = typer.Option(None, "--prefix", "-p", help="Key prefix (e.g. kf_live)"),
    expires_days: Optional[int] = typer.Option(None, "--expires", "-e", help="Expire in N days"),
    rate_requests: Optional[int] = typer.Option(None, "--rate-requests", help="Requests per window"),
    rate_window: str = typer.Option("1m", "--rate-window", help="Rate limit window (e.g. 1m, 1h)"),
    monthly_tokens: Optional[int] = typer.Option(None, "--monthly-tokens", help="Monthly token budget"),
    permissions: Optional[str] = typer.Option(None, "--permissions", help="Comma-separated permissions"),
    db: str = _DB_OPTION,
) -> None:
    """Create a new API key. [bold red]Plaintext shown once — save it.[/bold red]"""
    from datetime import timedelta
    from keysigil.core.engine import KeyForge

    kf = KeyForge(db)

    async def _run() -> None:
        await kf.setup()
        perms = [p.strip() for p in permissions.split(",")] if permissions else []
        rl = {"requests": rate_requests, "window": rate_window} if rate_requests else None
        tb = {"monthly": monthly_tokens} if monthly_tokens else None
        result = await kf.create_key(
            name=name,
            prefix=prefix,
            expires_in=timedelta(days=expires_days) if expires_days else None,
            rate_limit=rl,
            token_budget=tb,
            permissions=perms,
        )
        console.print(f"\n[bold yellow]⚠  Save this key — it will not be shown again.[/bold yellow]")
        console.print(f"\n[bold]Key:[/bold]  {result.plaintext}")
        console.print(f"[bold]ID:[/bold]   {result.key.id}")
        console.print(f"[bold]Name:[/bold] {result.key.name}")
        if result.key.expires_at:
            console.print(f"[bold]Expires:[/bold] {result.key.expires_at.strftime('%Y-%m-%d')}")

    asyncio.run(_run())


@app.command()
def verify(
    key: str = typer.Argument(..., help="API key to verify"),
    db: str = _DB_OPTION,
) -> None:
    """Verify an API key and show its status."""
    from keysigil.core.engine import KeyForge

    kf = KeyForge(db)

    async def _run() -> None:
        await kf.setup()
        result = await kf.verify(key)
        if result.valid:
            console.print(f"[green]✓ VALID[/green]  {result.key_name} ({result.key_id})")
            if result.permissions:
                console.print(f"  Permissions: {', '.join(result.permissions)}")
            if result.rate_limit_remaining is not None:
                console.print(f"  Rate limit remaining: {result.rate_limit_remaining}")
            if result.token_budget_remaining is not None:
                console.print(f"  Token budget remaining: {result.token_budget_remaining:,}")
        else:
            console.print(f"[red]✗ INVALID[/red]  {result.error}")
            raise typer.Exit(1)

    asyncio.run(_run())


@app.command(name="list")
def list_keys(
    prefix: Optional[str] = typer.Option(None, "--prefix", "-p", help="Filter by prefix"),
    db: str = _DB_OPTION,
) -> None:
    """List all API keys."""
    from keysigil.core.engine import KeyForge

    kf = KeyForge(db)

    async def _run() -> None:
        await kf.setup()
        keys = await kf.list_keys(prefix)
        if not keys:
            console.print("No keys found.")
            return
        table = Table(title="API Keys")
        table.add_column("ID", style="dim")
        table.add_column("Name")
        table.add_column("Prefix")
        table.add_column("Status")
        table.add_column("Expires")
        for k in keys:
            status_color = {"active": "green", "revoked": "red", "expired": "yellow", "rotating": "cyan"}.get(k.status.value, "white")
            table.add_row(
                k.id,
                k.name,
                k.prefix,
                f"[{status_color}]{k.status.value}[/{status_color}]",
                k.expires_at.strftime("%Y-%m-%d") if k.expires_at else "—",
            )
        console.print(table)

    asyncio.run(_run())


@app.command()
def revoke(
    key_id: str = typer.Argument(..., help="Key ID to revoke"),
    db: str = _DB_OPTION,
) -> None:
    """Revoke an API key immediately."""
    from keysigil.core.engine import KeyForge

    if not typer.confirm(f"Revoke {key_id}? This cannot be undone."):
        raise typer.Abort()

    kf = KeyForge(db)

    async def _run() -> None:
        await kf.setup()
        await kf.revoke_key(key_id)
        console.print(f"[red]✓[/red] Revoked: {key_id}")

    asyncio.run(_run())


@app.command()
def rotate(
    key_id: str = typer.Argument(..., help="Key ID to rotate"),
    grace_hours: int = typer.Option(24, "--grace", "-g", help="Grace period in hours"),
    db: str = _DB_OPTION,
) -> None:
    """Rotate a key. Old key stays valid during grace period."""
    from datetime import timedelta
    from keysigil.core.engine import KeyForge

    kf = KeyForge(db)

    async def _run() -> None:
        await kf.setup()
        result = await kf.rotate_key(key_id, timedelta(hours=grace_hours))
        console.print(f"\n[bold yellow]⚠  Save this new key — it will not be shown again.[/bold yellow]")
        console.print(f"\n[bold]New Key:[/bold]  {result.plaintext}")
        console.print(f"[bold]New ID:[/bold]   {result.key.id}")
        console.print(f"Old key {key_id} valid for {grace_hours}h more.")

    asyncio.run(_run())


@app.command()
def usage(
    key_id: str = typer.Argument(..., help="Key ID to inspect"),
    db: str = _DB_OPTION,
) -> None:
    """Show token usage stats for a key."""
    from keysigil.core.engine import KeyForge

    kf = KeyForge(db)

    async def _run() -> None:
        await kf.setup()
        stats = await kf.get_usage(key_id)
        console.print(f"\n[bold]Usage for {key_id}[/bold]")
        console.print(f"  Total tokens:  {stats.total_tokens:,}")
        console.print(f"  Input tokens:  {stats.input_tokens:,}")
        console.print(f"  Output tokens: {stats.output_tokens:,}")
        console.print(f"  Records:       {stats.record_count}")
        if stats.by_model:
            console.print("\n  [bold]By model:[/bold]")
            for model, tokens in stats.by_model.items():
                console.print(f"    {model}: {tokens:,}")

    asyncio.run(_run())


@app.command()
def serve(host: str = typer.Option("localhost", "--host"), port: int = typer.Option(8080, "--port")) -> None:
    """Start the MCP server for LLM agent integration."""
    try:
        from keysigil.mcp.server import run
        run(host=host, port=port)
    except ImportError:
        console.print("[red]MCP not installed.[/red] Run: pip install 'keysigil[mcp]'")
        raise typer.Exit(1)
