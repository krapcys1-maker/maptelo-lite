"""Command line: ``minierp serve``."""

from __future__ import annotations

import argparse
from datetime import date

import uvicorn

from minierp.app import create_app
from minierp.config import CHAOS_PRESETS, Settings


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="minierp", description="MiniERP testbed for Maptelo.")
    commands = parser.add_subparsers(dest="command", required=True)
    serve = commands.add_parser("serve", help="Run the web application.")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)
    serve.add_argument("--seed", type=int, default=42, help="Seed for every chaos decision.")
    serve.add_argument("--chaos", choices=sorted(CHAOS_PRESETS), default="off")
    serve.add_argument(
        "--layout", choices=["a", "b"], default="a", help="'b' simulates a redesign."
    )
    serve.add_argument(
        "--today", type=date.fromisoformat, help="Pin the business date (YYYY-MM-DD)."
    )
    args = parser.parse_args(argv)

    chaos = CHAOS_PRESETS[args.chaos].model_copy(update={"layout": args.layout})
    settings = Settings(seed=args.seed, chaos=chaos, today=args.today)
    uvicorn.run(create_app(settings), host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
