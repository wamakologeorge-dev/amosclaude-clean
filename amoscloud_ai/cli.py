"""Command-line interface for Amoscloud AI."""

import sys

import click
import uvicorn

from amoscloud_ai import __version__
from amoscloud_ai.config import settings


@click.group()
@click.version_option(__version__, prog_name="amoscloud-ai")
def cli() -> None:
    """Amoscloud AI – Self-hosted CI/CD & Deployment Automation."""


@cli.command()
@click.option("--host", default=settings.host, show_default=True, help="Bind host")
@click.option("--port", default=settings.port, show_default=True, type=int, help="Bind port")
@click.option("--workers", default=settings.workers, show_default=True, type=int, help="Worker count")
@click.option("--reload", is_flag=True, default=False, help="Enable auto-reload (dev only)")
def serve(host: str, port: int, workers: int, reload: bool) -> None:
    """Start the Amoscloud AI API server."""
    click.echo(f"Starting Amoscloud AI v{__version__} on {host}:{port} …")
    uvicorn.run(
        "amoscloud_ai.main:app",
        host=host,
        port=port,
        workers=workers,
        reload=reload,
        log_level=settings.log_level.lower(),
    )


@cli.command()
@click.option("--concurrency", default=2, show_default=True, type=int, help="Worker concurrency")
def worker(concurrency: int) -> None:
    """Start the Celery background worker."""
    from amoscloud_ai.worker import celery_app

    click.echo(f"Starting Amoscloud AI worker (concurrency={concurrency}) …")
    celery_app.worker_main(
        argv=["worker", "--loglevel", settings.log_level.lower(), "-c", str(concurrency)]
    )


@cli.command()
def version() -> None:
    """Print the application version."""
    click.echo(f"amoscloud-ai {__version__}")


def main() -> None:
    cli()


if __name__ == "__main__":
    main()
