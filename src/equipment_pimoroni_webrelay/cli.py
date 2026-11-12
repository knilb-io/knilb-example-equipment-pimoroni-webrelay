"""Command-line entry point: ``equipment-pimoroni-webrelay``."""

from __future__ import annotations

import argparse
import logging
import sys
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any, TextIO

import yaml

from equipment_pimoroni_webrelay import __version__
from equipment_pimoroni_webrelay.config import PREFIX, Settings, load_settings

Runner = Callable[..., Any]


def build_parser() -> argparse.ArgumentParser:
    """Build the argument parser with one sub-command per operation."""
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument(
        "--env-file", type=Path, help="read settings from this .env file as well"
    )
    parser = argparse.ArgumentParser(
        prog="equipment-pimoroni-webrelay",
        description="A web relay (state.json API) on a Pimoroni Automation HAT.",
    )
    commands = parser.add_subparsers(dest="command", required=True)

    serve = commands.add_parser("serve", parents=[common], help="run the REST service")
    serve.add_argument("--host", help=f"bind address ({PREFIX}HOST)")
    serve.add_argument("--port", type=int, help=f"bind port ({PREFIX}PORT)")
    serve.add_argument("--log-level", help=f"log level ({PREFIX}LOG_LEVEL)")
    serve.add_argument(
        "--fake",
        action="store_true",
        help=f"serve a fake board (no HAT needed; {PREFIX}FAKE)",
    )
    serve.add_argument(
        "--fake-toggle-s",
        type=float,
        help=f"with --fake, flip the input every N seconds ({PREFIX}FAKE_TOGGLE_S)",
    )

    contract = commands.add_parser(
        "contract", parents=[common], help="write the OpenAPI document this serves"
    )
    contract.add_argument("-o", "--output", type=Path, help="file to write (stdout)")

    commands.add_parser("version", parents=[common], help="print the package version")
    return parser


def main(
    argv: Sequence[str] | None = None,
    *,
    run_server: Runner | None = None,
    out: TextIO | None = None,
) -> int:
    """Run the CLI and return a process exit code."""
    args = build_parser().parse_args(argv)
    out = out or sys.stdout
    if args.command == "version":
        print(__version__, file=out)
        return 0
    if args.command == "contract":
        return _contract(args, out)
    try:
        settings = load_settings(args.env_file)
    except (FileNotFoundError, ValueError) as exc:
        print(f"equipment-pimoroni-webrelay: {exc}", file=sys.stderr)
        return 2
    return _serve(args, settings, run_server)


def _serve(
    args: argparse.Namespace, settings: Settings, run_server: Runner | None
) -> int:
    from equipment_pimoroni_webrelay.api import create_app

    names = (("host", "host"), ("port", "port"), ("log_level", "log_level"))
    overrides: dict[str, Any] = {
        key: getattr(args, attr)
        for attr, key in (*names, ("fake_toggle_s", "fake_toggle_s"))
        if getattr(args, attr) is not None
    }
    if args.fake:
        overrides["fake"] = True
    settings = Settings.model_validate({**settings.model_dump(), **overrides})
    logging.basicConfig(
        level=settings.log_level.upper(), format="%(message)s", force=True
    )
    app = create_app(settings)
    if run_server is None:  # pragma: no cover - exercised by running the service
        import uvicorn

        run_server = uvicorn.run
    run_server(
        app,
        host=settings.host,
        port=settings.port,
        log_level=settings.log_level.lower(),
        workers=1,  # the device must be a singleton
    )
    return 0


def _contract(args: argparse.Namespace, out: TextIO) -> int:
    from equipment_pimoroni_webrelay.api import load_contract

    text = yaml.safe_dump(load_contract(), sort_keys=False, allow_unicode=True)
    if args.output is None:
        out.write(text)
    else:
        args.output.write_text(text, encoding="utf-8")
    return 0
