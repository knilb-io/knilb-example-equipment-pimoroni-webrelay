from __future__ import annotations

import pytest

from equipment_pimoroni_webrelay.board import FakeBoard
from equipment_pimoroni_webrelay.clock import FakeClock
from equipment_pimoroni_webrelay.device import (
    Device,
    DeviceConfig,
    format_register,
    format_two,
)
from tests.conftest import OFF_V, ON_V, settle


def state(device: Device) -> dict[str, str]:
    return device.state(1_794_081_304)


def test_unknown_before_first_sample(device: Device) -> None:
    body = state(device)
    assert body["digitalInput1"] == ""
    assert body["vin"] == ""
    assert body["relay1"] == "0"
    assert body["utcTime"] == "1794081304"
    assert body["timezoneOffset"] == "0"
    assert body["serialNumber"] == "B8:27:EB:00:00:01"


def test_input_off_then_on_counts_one_edge(
    device: Device, board: FakeBoard, clock: FakeClock
) -> None:
    settle(device, clock)
    assert state(device)["digitalInput1"] == "0"
    assert state(device)["vin"] == "12.2"
    board.input_volts = ON_V
    device.step()
    assert state(device)["digitalInput1"] == "0"  # one sample is not enough
    clock.advance(0.02)
    device.step()
    body = state(device)
    assert body["digitalInput1"] == "1"
    assert body["count1"] == "1.00"
    assert body["frequency1"] == "1.00"
    assert board.input_light is True


def test_first_reading_on_is_not_an_edge(
    device: Device, board: FakeBoard, clock: FakeClock
) -> None:
    board.input_volts = ON_V
    settle(device, clock)
    assert state(device)["digitalInput1"] == "1"
    assert state(device)["count1"] == "0.00"


def test_between_thresholds_holds(
    device: Device, board: FakeBoard, clock: FakeClock
) -> None:
    settle(device, clock)
    board.input_volts = 3.0
    settle(device, clock, 5)
    assert state(device)["digitalInput1"] == "0"


def test_glitch_is_ignored(device: Device, board: FakeBoard, clock: FakeClock) -> None:
    settle(device, clock)
    board.input_volts = ON_V
    settle(device, clock, 1)
    board.input_volts = OFF_V
    settle(device, clock, 3)
    assert state(device)["count1"] == "0.00"


def test_pending_reading_restarts_when_it_changes(clock: FakeClock) -> None:
    board = FakeBoard(OFF_V)
    device = Device(board, DeviceConfig(debounce_samples=3), clock=clock)
    device.open()
    settle(device, clock, 3)
    board.input_volts = ON_V
    settle(device, clock, 2)
    board.input_volts = 3.0  # hold: clears the pending ON
    settle(device, clock, 1)
    board.input_volts = ON_V
    settle(device, clock, 2)
    assert state(device)["digitalInput1"] == "0"
    settle(device, clock, 1)
    assert state(device)["digitalInput1"] == "1"


def test_on_time_and_total_on_time(
    device: Device, board: FakeBoard, clock: FakeClock
) -> None:
    settle(device, clock)
    board.input_volts = ON_V
    settle(device, clock)
    clock.advance(2.0)
    device.step()
    body = state(device)
    assert body["onTime1"] == "2.02"
    assert body["totalOnTime1"] == "2.02"
    board.input_volts = OFF_V
    settle(device, clock)
    clock.advance(5.0)
    device.step()
    off = state(device)
    assert off["digitalInput1"] == "0"
    assert off["onTime1"] == "2.04"  # held while off
    board.input_volts = ON_V
    settle(device, clock)
    again = state(device)
    assert again["count1"] == "2.00"
    assert float(again["onTime1"]) < 0.1  # restarted on the new edge


def test_frequency_counts_edges_in_the_window(
    device: Device, board: FakeBoard, clock: FakeClock
) -> None:
    settle(device, clock)
    for _ in range(3):
        board.input_volts = ON_V
        settle(device, clock)
        board.input_volts = OFF_V
        settle(device, clock)
    assert state(device)["frequency1"] == "3.00"
    clock.advance(1.5)
    device.step()
    assert state(device)["frequency1"] == "0.00"


def test_relay_on_off(device: Device, board: FakeBoard) -> None:
    device.apply([("relay1", "1")])
    assert board.relay is True
    assert state(device)["relay1"] == "1"
    device.apply([("relay1", "0")])
    assert board.relay is False
    assert state(device)["relay1"] == "0"


def test_pulse_uses_the_default_time(
    device: Device, board: FakeBoard, clock: FakeClock
) -> None:
    device.apply([("relay1", "2")])
    assert board.relay is True
    clock.advance(1.4)
    device.step()
    assert board.relay is True
    clock.advance(0.2)
    device.step()
    assert board.relay is False
    assert state(device)["relay1"] == "0"


def test_pulse_time_applies_once_when_it_comes_first(
    device: Device, board: FakeBoard, clock: FakeClock
) -> None:
    device.apply([("pulseTime1", "5"), ("relay1", "2")])
    clock.advance(4.9)
    device.step()
    assert board.relay is True
    clock.advance(0.2)
    device.step()
    assert board.relay is False
    device.apply([("relay1", "2")])  # back to the default
    clock.advance(1.6)
    device.step()
    assert board.relay is False


def test_pulse_time_after_relay_does_not_change_that_pulse(
    device: Device, board: FakeBoard, clock: FakeClock
) -> None:
    device.apply([("relay1", "2"), ("pulseTime1", "5")])
    clock.advance(1.6)
    device.step()
    assert board.relay is False


@pytest.mark.parametrize("value", ["0.05", "100000", "abc", "nan", "inf"])
def test_pulse_time_out_of_range_is_ignored(
    device: Device, board: FakeBoard, clock: FakeClock, value: str
) -> None:
    device.apply([("pulseTime1", value), ("relay1", "2")])
    clock.advance(1.6)
    device.step()
    assert board.relay is False


def test_on_or_off_cancels_a_pulse(
    device: Device, board: FakeBoard, clock: FakeClock
) -> None:
    device.apply([("relay1", "2"), ("relay1", "1")])
    clock.advance(2.0)
    device.step()
    assert board.relay is True
    device.apply([("relay1", "2"), ("relay1", "0")])
    assert board.relay is False


def test_setters(device: Device, board: FakeBoard, clock: FakeClock) -> None:
    device.apply(
        [
            ("register1", "10.5"),
            ("count1", "200"),
            ("onTime1", "0"),
            ("totalOnTime1", "-3"),
            ("relay1", "7"),
            ("unknown", "1"),
            ("register1", "not a number"),
        ]
    )
    body = state(device)
    assert body["register1"] == "10.5"
    assert body["count1"] == "200.00"
    assert body["onTime1"] == "0.00"
    assert body["totalOnTime1"] == "0.00"
    assert body["relay1"] == "0"


def test_board_missing_then_found(clock: FakeClock) -> None:
    board = FakeBoard(OFF_V)
    board.fail_open = True
    device = Device(board, DeviceConfig(), clock=clock)
    device.open()
    assert "not detected" in device.last_error
    device.apply([("relay1", "1")])  # remembered while the board is away
    settle(device, clock)
    assert state(device)["digitalInput1"] == ""
    board.fail_open = False
    clock.advance(5.0)
    settle(device, clock)
    assert state(device)["digitalInput1"] == "0"
    assert board.relay is True
    assert device.last_error == ""


def test_io_failure_makes_the_input_unknown(
    device: Device, board: FakeBoard, clock: FakeClock
) -> None:
    settle(device, clock)
    board.fail_io = True
    clock.advance(1.5)
    device.step()
    body = state(device)
    assert body["digitalInput1"] == ""
    assert body["vin"] == ""
    assert "I/O failed" in device.last_error
    device.apply([("relay1", "1")])
    assert body["relay1"] == "0"
    assert state(device)["relay1"] == "1"  # requested; the write is retried
    board.fail_io = False
    settle(device, clock)
    assert state(device)["digitalInput1"] == "0"
    assert board.relay is True


def test_no_vin_channel(clock: FakeClock) -> None:
    device = Device(FakeBoard(OFF_V, None), DeviceConfig(), clock=clock)
    device.open()
    settle(device, clock)
    assert device.state(0)["vin"] == ""


def test_start_and_stop(board: FakeBoard, clock: FakeClock) -> None:
    device = Device(board, DeviceConfig(), clock=clock)
    device.start()
    device.stop()
    assert board.opened and board.closed
    device.stop()  # idempotent


def test_formats() -> None:
    assert format_two(0) == "0.00"
    assert format_register(0.0) == "0"
    assert format_register(10.5) == "10.5"
