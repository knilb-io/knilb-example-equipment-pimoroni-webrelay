from __future__ import annotations

import sys
from types import ModuleType, SimpleNamespace
from typing import Any

import pytest

from equipment_pimoroni_webrelay.board import AutomationHatBoard, BoardError, FakeBoard


class Pin:
    def __init__(self, value: float = 0.0) -> None:
        self.value = value
        self.written: list[int] = []
        self.fail = False

    def read(self) -> float:
        if self.fail:
            raise OSError("i2c")
        return self.value

    def write(self, value: int) -> None:
        if self.fail:
            raise OSError("gpio")
        self.written.append(value)


def fake_module(fail_setup: bool = False) -> Any:
    def analog() -> Any:
        return SimpleNamespace(read=Pin(19.0).read, light=Pin())

    analogs = {name: analog() for name in ("one", "two", "three")}
    analogs["two"] = SimpleNamespace(read=Pin(12.1).read, light=Pin())
    relay = Pin()
    relay.light_no = Pin()  # type: ignore[attr-defined]
    relay.light_nc = Pin()  # type: ignore[attr-defined]

    def setup() -> None:
        if fail_setup:
            raise RuntimeError("no ADC")

    return SimpleNamespace(
        setup=setup,
        enable_auto_lights=lambda on: None,
        analog=SimpleNamespace(**analogs),
        relay=SimpleNamespace(one=relay, two=Pin(), three=Pin()),
        light=SimpleNamespace(power=Pin()),
    )


def test_hat_reads_and_drives() -> None:
    module = fake_module()
    board = AutomationHatBoard(1, 1, 2, module=module)
    board.open()
    assert board.read_input_volts() == 19.0
    assert board.read_vin_volts() == 12.1
    board.write_relay(True)
    relay = module.relay.one
    assert relay.written[-1] == 1
    assert (relay.light_no.written[-1], relay.light_nc.written[-1]) == (1, 0)
    board.set_input_light(True)
    board.close()
    assert relay.written[-1] == 0
    assert module.light.power.written == [1, 0]


def test_hat_without_vin() -> None:
    board = AutomationHatBoard(1, 1, module=fake_module())
    board.open()
    assert board.read_vin_volts() is None


def test_hat_not_detected() -> None:
    board = AutomationHatBoard(1, 1, module=fake_module(True))
    with pytest.raises(BoardError, match="not detected"):
        board.open()


def test_hat_io_errors() -> None:
    module = fake_module()
    pin = Pin()
    pin.fail = True
    module.analog.one = SimpleNamespace(read=pin.read, light=Pin())
    module.analog.two = SimpleNamespace(read=pin.read, light=Pin())
    module.relay.one = pin
    board = AutomationHatBoard(1, 1, 2, module=module)
    board.open()
    with pytest.raises(BoardError, match="analog"):
        board.read_input_volts()
    with pytest.raises(BoardError, match="analog"):
        board.read_vin_volts()
    with pytest.raises(BoardError, match="relay"):
        board.write_relay(True)


def test_missing_driver(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "automationhat", None)
    with pytest.raises(BoardError, match="not installed"):
        AutomationHatBoard(1, 1).open()


def test_driver_imported_lazily(monkeypatch: pytest.MonkeyPatch) -> None:
    module = ModuleType("automationhat")
    for key, value in vars(fake_module()).items():
        setattr(module, key, value)
    monkeypatch.setitem(sys.modules, "automationhat", module)
    board = AutomationHatBoard(1, 1)
    board.open()
    assert board.read_input_volts() == 19.0


def test_fake_toggle() -> None:
    now = [0.0]
    board = FakeBoard(toggle_s=1.0, monotonic=lambda: now[0])
    assert board.read_input_volts() == 0.0
    now[0] = 1.5
    assert board.read_input_volts() == 24.0
