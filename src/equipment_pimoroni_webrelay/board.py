"""The board behind the device: one analog input, one relay, and the LEDs.

``AutomationHatBoard`` is the only code that imports Pimoroni's ``automationhat``,
and it does so lazily, so the service imports cleanly on macOS and the driver is an
optional extra (``pip install 'equipment-pimoroni-webrelay[hat]'``). ``FakeBoard``
serves the same interface for development and tests.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from types import ModuleType
from typing import Any, Protocol

CHANNEL_NAMES: dict[int, str] = {1: "one", 2: "two", 3: "three"}
"""``automationhat`` names its channels ``one``, ``two`` and ``three``."""

INSTALL_HINT = "pip install 'equipment-pimoroni-webrelay[hat]'"


class BoardError(RuntimeError):
    """The board is absent, its driver is not installed, or an I/O call failed."""


class Board(Protocol):
    """What the device needs from the hardware.

    Only the device's own thread and its lock holders call these methods, so
    implementations need not be thread-safe.
    """

    @property
    def name(self) -> str:
        """Short name for logs (``automationhat`` or ``fake``)."""
        ...

    def open(self) -> None:
        """Detect the board and take over its LEDs.

        Raises:
            BoardError: the driver is not installed or the board is not detected.
        """
        ...

    def read_input_volts(self) -> float:
        """Return the voltage on the input channel.

        Raises:
            BoardError: the read failed.
        """
        ...

    def read_vin_volts(self) -> float | None:
        """Return the voltage on the Vin channel, or None when none is wired.

        Raises:
            BoardError: the read failed.
        """
        ...

    def write_relay(self, on: bool) -> None:
        """Energize or release the relay and light its NO or NC LED.

        Raises:
            BoardError: the write failed.
        """
        ...

    def set_input_light(self, on: bool) -> None:
        """Light the LED beside the input's ADC terminal."""
        ...

    def close(self) -> None:
        """Release the relay, turn the LEDs off, and let the board go."""
        ...


class AutomationHatBoard:
    """The Pimoroni Automation HAT through the ``automationhat`` library.

    The input is read from a 0-24 V analog channel, whose on-board divider holds an
    unconnected input at a defined 0 V. The library's own light thread is stopped
    in :meth:`open`, and this class drives the LEDs from the debounced state.
    """

    name = "automationhat"

    def __init__(
        self,
        input_channel: int,
        relay_channel: int,
        vin_channel: int = 0,
        *,
        module: ModuleType | None = None,
    ) -> None:
        self._input_channel = input_channel
        self._relay_channel = relay_channel
        self._vin_channel = vin_channel
        self._hat: Any = module
        self._input: Any = None
        self._vin: Any = None
        self._relay: Any = None

    def open(self) -> None:
        """Import the driver, detect the ADC, and disable the library's auto-lights."""
        if self._hat is None:
            try:
                import automationhat
            except ImportError as exc:
                raise BoardError(
                    f"automationhat is not installed ({INSTALL_HINT})"
                ) from exc
            self._hat = automationhat
        try:
            self._hat.setup()
            self._hat.enable_auto_lights(False)
        except (RuntimeError, OSError, ImportError) as exc:
            raise BoardError(f"Automation HAT not detected: {exc}") from exc
        self._input = getattr(self._hat.analog, CHANNEL_NAMES[self._input_channel])
        if self._vin_channel:
            self._vin = getattr(self._hat.analog, CHANNEL_NAMES[self._vin_channel])
        self._relay = getattr(self._hat.relay, CHANNEL_NAMES[self._relay_channel])
        self._hat.light.power.write(1)

    def read_input_volts(self) -> float:
        """Read the input channel, in volts."""
        try:
            return float(self._input.read())
        except (OSError, RuntimeError) as exc:
            raise BoardError(f"analog read failed: {exc}") from exc

    def read_vin_volts(self) -> float | None:
        """Read the Vin channel, in volts, when one is configured."""
        if self._vin is None:
            return None
        try:
            return float(self._vin.read())
        except (OSError, RuntimeError) as exc:
            raise BoardError(f"analog read failed: {exc}") from exc

    def write_relay(self, on: bool) -> None:
        """Drive the relay coil and its NO and NC LEDs."""
        try:
            self._relay.write(1 if on else 0)
            self._relay.light_no.write(1 if on else 0)
            self._relay.light_nc.write(0 if on else 1)
        except (OSError, RuntimeError) as exc:
            raise BoardError(f"relay write failed: {exc}") from exc

    def set_input_light(self, on: bool) -> None:
        """Drive the LED beside the input's ADC terminal."""
        self._input.light.write(1 if on else 0)

    def close(self) -> None:
        """Release the relay and turn off every LED this service drove."""
        self._relay.write(0)
        for light in (
            self._relay.light_no,
            self._relay.light_nc,
            self._input.light,
            self._hat.light.power,
        ):
            light.write(0)


class FakeBoard:
    """A scriptable board for development and tests.

    Set :attr:`input_volts` and :attr:`vin_volts` to simulate the wiring.
    ``toggle_s`` flips the input between 0 V and ``toggle_volts`` on a fixed period,
    so the counters can be watched from a browser. ``fail_open`` and ``fail_io``
    simulate a missing HAT and an I/O fault. :attr:`relay` and :attr:`input_light`
    record what was driven.
    """

    name = "fake"

    def __init__(
        self,
        input_volts: float = 0.0,
        vin_volts: float | None = 12.0,
        *,
        toggle_s: float = 0.0,
        toggle_volts: float = 24.0,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self.input_volts = input_volts
        self.vin_volts = vin_volts
        self.toggle_s = toggle_s
        self.toggle_volts = toggle_volts
        self.fail_open = False
        self.fail_io = False
        self.opened = False
        self.closed = False
        self.relay = False
        self.relay_writes = 0
        self.input_light = False
        self._monotonic = monotonic

    def open(self) -> None:
        """Pretend to detect the board unless ``fail_open`` is set."""
        if self.fail_open:
            raise BoardError("fake board: not detected")
        self.opened = True

    def _check(self) -> None:
        if self.fail_io:
            raise BoardError("fake board: I/O failed")

    def read_input_volts(self) -> float:
        """Return the scripted input voltage."""
        self._check()
        if self.toggle_s > 0:
            phase = int(self._monotonic() / self.toggle_s) % 2
            self.input_volts = self.toggle_volts if phase else 0.0
        return self.input_volts

    def read_vin_volts(self) -> float | None:
        """Return the scripted Vin."""
        self._check()
        return self.vin_volts

    def write_relay(self, on: bool) -> None:
        """Record the relay state."""
        self._check()
        self.relay = on
        self.relay_writes += 1

    def set_input_light(self, on: bool) -> None:
        """Record the LED state."""
        self.input_light = on

    def close(self) -> None:
        """Record that the board was released."""
        self.closed = True
        self.relay = False
        self.input_light = False
