"""Command-line interface: ``python -m certprep serve`` / ``validate``."""

from __future__ import annotations

import argparse
import logging
import sys
from collections.abc import Sequence
from dataclasses import replace

from certprep import __version__
from certprep.catalog import CatalogError, load_catalog
from certprep.config import Settings
from certprep.questions import validate_catalog
from certprep.server import Application, create_server

log = logging.getLogger("certprep")


def _serve(settings: Settings) -> int:
    app = Application.create(settings)
    httpd = create_server(app)
    shown_host = "localhost" if settings.host in ("0.0.0.0", "") else settings.host
    base = f"http://{shown_host}:{settings.port}"
    print("=" * 60)
    print(f"  Certification practice exams v{__version__}")
    print(f"  Open:     {base}/")
    print(f"  Report:   {base}/report")
    print(f"  Database: {settings.db_path}")
    print("  Press Ctrl+C to stop.")
    print("=" * 60)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        httpd.server_close()
    return 0


def _validate(settings: Settings) -> int:
    try:
        catalog = load_catalog(settings.catalog_path)
    except (CatalogError, KeyError, ValueError, OSError) as exc:
        print(f"catalog error: {exc}", file=sys.stderr)
        return 1
    problems = validate_catalog(catalog, settings.questions_dir)
    for problem in problems:
        print(f"  ✗ {problem}", file=sys.stderr)
    if problems:
        print(f"{len(problems)} problem(s) found.", file=sys.stderr)
        return 1
    print(f"OK: {sum(1 for _ in catalog)} exams validated.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="certprep", description=__doc__)
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command")
    serve = sub.add_parser("serve", help="run the exam server (default)")
    serve.add_argument("--host", help="interface to bind (default 0.0.0.0)")
    serve.add_argument("--port", type=int, help="port to listen on (default 8000)")
    sub.add_parser("validate", help="check the catalog and question banks")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="  %(message)s")
    settings = Settings.from_env()
    if args.command == "validate":
        return _validate(settings)
    if getattr(args, "host", None) or getattr(args, "port", None):
        settings = replace(
            settings,
            host=args.host or settings.host,
            port=args.port or settings.port,
        )
    return _serve(settings)
