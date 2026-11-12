"""Shared fixtures: a fake clock and board, a hand-driven device, and the app."""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from equipment_pimoroni_webrelay.api import create_app
from equipment_pimoroni_webrelay.board import FakeBoard
from equipment_pimoroni_webrelay.clock import FakeClock
from equipment_pimoroni_webrelay.config import Settings
from equipment_pimoroni_webrelay.device import Device, DeviceConfig

ON_V = 19.0
OFF_V = 0.01


@pytest.fixture(autouse=True)
def isolated(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    for key in list(os.environ):
        if key.startswith("EQUIPMENT_PIMORONI_WEBRELAY_"):
            monkeypatch.delenv(key, raising=False)


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def board() -> FakeBoard:
    return FakeBoard(OFF_V, 12.2)


@pytest.fixture
def config() -> DeviceConfig:
    return DeviceConfig(serial_number="B8:27:EB:00:00:01")


@pytest.fixture
def device(board: FakeBoard, config: DeviceConfig, clock: FakeClock) -> Device:
    """A device that is opened but not threaded: tests call ``step()`` by hand."""
    device = Device(board, config, clock=clock)
    device.open()
    return device


def settle(device: Device, clock: FakeClock, samples: int = 2) -> None:
    """Run ``samples`` cycles, advancing the fake clock by one period each."""
    for _ in range(samples):
        device.step()
        clock.advance(device.config.period_s)


class ManualDevice(Device):
    """A device whose thread never starts, so tests drive it with ``step()``."""

    def start(self) -> None:
        pass


@pytest.fixture
def manual(board: FakeBoard, config: DeviceConfig, clock: FakeClock) -> ManualDevice:
    device = ManualDevice(board, config, clock=clock)
    device.open()
    return device


def make_client(device: Device, **settings: str) -> Iterator[TestClient]:
    app = create_app(Settings.model_validate(settings), device=device)
    with TestClient(app) as client:
        yield client


@pytest.fixture
def client(manual: ManualDevice) -> Iterator[TestClient]:
    yield from make_client(manual)
