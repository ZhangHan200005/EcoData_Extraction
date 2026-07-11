"""Command-line entry point."""

from __future__ import annotations

import argparse
from pathlib import Path

from .pipeline import run_pipeline
from .server import serve


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ecodata-mvp", description="Traceable human-in-the-loop literature data extraction MVP")
    parser.add_argument("--root", type=Path, default=Path.cwd(), help="MVP project root")
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser("run", help="Parse PDFs and create a new data package")
    run.add_argument("--input", type=Path, help="Directory containing PDFs")
    web = commands.add_parser("serve", help="Start local upload and review interface")
    web.add_argument("--host", default="127.0.0.1")
    web.add_argument("--port", type=int, default=8765)
    web.add_argument("--no-browser", action="store_true")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    root = args.root.resolve()
    if args.command == "run":
        output = run_pipeline(root, args.input)
        print(f"Completed: {output}")
        print(f"QC report: {output / 'quality_report.html'}")
    elif args.command == "serve":
        serve(root, args.host, args.port, not args.no_browser)


if __name__ == "__main__":
    main()

