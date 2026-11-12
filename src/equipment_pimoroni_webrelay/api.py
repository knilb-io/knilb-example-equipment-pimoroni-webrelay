"""The FastAPI application: the web relay's ``GET /state.json``.

The contract is the committed ``webrelay-openapi.yaml``, served unchanged at
``/openapi.yaml`` and ``/openapi.json`` and used by ``/docs``. Every control is a
query parameter on the same GET, applied in the order sent, as on the device.
"""

from __future__ import annotations

import base64
import binascii
import secrets
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from importlib.resources import files
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl

import yaml
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response

from equipment_pimoroni_webrelay import __version__
from equipment_pimoroni_webrelay.board import AutomationHatBoard, Board, FakeBoard
from equipment_pimoroni_webrelay.config import RELAY_CHANNEL, Settings
from equipment_pimoroni_webrelay.device import Device, DeviceConfig

CONTRACT_NAME = "webrelay-openapi.yaml"
NET_ADDRESS = Path("/sys/class/net/eth0/address")
NO_SERIAL = "00:00:00:00:00:00"


def load_contract() -> dict[str, Any]:
    """Return the web relay OpenAPI document shipped with the package."""
    text = (
        files("equipment_pimoroni_webrelay")
        .joinpath(CONTRACT_NAME)
        .read_text(encoding="utf-8")
    )
    document: dict[str, Any] = yaml.safe_load(text)
    return document


def serial_number(settings: Settings, address_file: Path = NET_ADDRESS) -> str:
    """The configured serial number, else the Pi's Ethernet MAC address."""
    if settings.serial_number:
        return settings.serial_number
    try:
        return address_file.read_text(encoding="ascii").strip().upper() or NO_SERIAL
    except OSError:
        return NO_SERIAL


def build_board(settings: Settings) -> Board:
    """The fake board when ``settings.fake`` is set, else the Automation HAT."""
    if settings.fake:
        return FakeBoard(
            settings.fake_volts, settings.fake_vin, toggle_s=settings.fake_toggle_s
        )
    return AutomationHatBoard(
        settings.input_channel, RELAY_CHANNEL, settings.vin_channel
    )


def build_device(settings: Settings, board: Board | None = None) -> Device:
    """A device configured from ``settings``."""
    config = DeviceConfig(
        period_s=settings.sample_period_ms / 1000,
        on_min_v=settings.on_min_v,
        off_max_v=settings.off_max_v,
        debounce_samples=settings.debounce_samples,
        pulse_time_s=settings.pulse_time_s,
        frequency_window_s=settings.frequency_window_s,
        timezone_offset_s=settings.timezone_offset_s,
        serial_number=serial_number(settings),
    )
    return Device(board or build_board(settings), config)


def authorized(header: str | None, password: str) -> bool:
    """Check HTTP Basic credentials. With no password set, everyone is allowed.

    The device's usernames are fixed, so only the password is compared.
    """
    if not password:
        return True
    if not header or not header.startswith("Basic "):
        return False
    try:
        decoded = base64.b64decode(header[6:], validate=True).decode("utf-8")
    except (binascii.Error, UnicodeDecodeError):
        return False
    _, separator, given = decoded.partition(":")
    return bool(separator) and secrets.compare_digest(given, password)


def create_app(settings: Settings, *, device: Device | None = None) -> FastAPI:
    """Build the application around one device (a singleton: one worker only)."""
    device = device or build_device(settings)
    contract = load_contract()

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        device.start()
        try:
            yield
        finally:
            device.stop()

    app = FastAPI(
        title=contract["info"]["title"],
        version=__version__,
        lifespan=lifespan,
        redoc_url=None,
    )
    app.state.settings = settings
    app.state.device = device
    app.openapi = lambda: contract  # type: ignore[method-assign]

    @app.get("/state.json", include_in_schema=False)
    def get_state(request: Request) -> Response:
        if not authorized(request.headers.get("authorization"), settings.password):
            return Response(
                status_code=401,
                headers={"WWW-Authenticate": 'Basic realm="state.json"'},
            )
        device.apply(parse_qsl(request.url.query, keep_blank_values=True))
        return JSONResponse(device.state(int(time.time())))

    @app.get("/openapi.yaml", include_in_schema=False)
    def openapi_yaml() -> Response:
        text = yaml.safe_dump(contract, sort_keys=False, allow_unicode=True)
        return Response(text, media_type="application/yaml")

    return app
