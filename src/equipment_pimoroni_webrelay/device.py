"""The web relay itself: input counters, relay control, register, and state.json.

One :class:`Device` owns the board. Its thread samples the input every
``period_s``, debounces it with hysteresis, and keeps the input counters
(``count1``, ``onTime1``, ``totalOnTime1``, ``frequency1``). It also ends relay
pulses on time. HTTP handlers call :meth:`Device.apply` with the request's query
parameters, in the order they were sent, and then read :meth:`Device.state`.
Both take the lock, so a handler always sees a consistent state.
"""

from __future__ import annotations

import logging
import math
import threading
from collections import deque
from collections.abc import Iterable
from dataclasses import dataclass

from equipment_pimoroni_webrelay.board import Board, BoardError
from equipment_pimoroni_webrelay.clock import Clock, SystemClock

logger = logging.getLogger("equipment_pimoroni_webrelay.device")

OFF = 0
ON = 1
UNKNOWN = -1

RELAY_OFF = "0"
RELAY_ON = "1"
RELAY_PULSE = "2"

PULSE_TIME_MIN_S = 0.1
PULSE_TIME_MAX_S = 86_400.0


@dataclass
class DeviceConfig:
    """Timing, thresholds and the always-present fields."""

    period_s: float = 0.02
    on_min_v: float = 4.0
    off_max_v: float = 1.5
    debounce_samples: int = 2
    pulse_time_s: float = 1.5
    frequency_window_s: float = 1.0
    timezone_offset_s: int = 0
    serial_number: str = "00:00:00:00:00:00"
    reopen_every_s: float = 5.0
    stale_after_s: float = 1.0


def _number(text: str) -> float | None:
    """Parse a finite number, or return None."""
    try:
        value = float(text)
    except ValueError:
        return None
    return value if math.isfinite(value) else None


def format_two(value: float) -> str:
    """Format like the device's counters: ``"0.00"``."""
    return f"{value:.2f}"


def format_register(value: float) -> str:
    """Format a register value without a trailing ``.0``: ``"0"``, ``"10.5"``."""
    return f"{value:g}"


class Device:
    """Owns the board; computes the input state and drives the relay."""

    def __init__(
        self,
        board: Board,
        config: DeviceConfig | None = None,
        *,
        clock: Clock | None = None,
    ) -> None:
        self.board = board
        self.config = config or DeviceConfig()
        self._clock = clock or SystemClock()
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._opened = False
        self._next_open_at = 0.0
        self._last_ok: float | None = None
        self._last_error = ""
        self._input = UNKNOWN
        self._pending: int | None = None
        self._pending_count = 0
        self._last_tick: float | None = None
        self._count = 0.0
        self._on_time = 0.0
        self._total_on_time = 0.0
        self._edges: deque[float] = deque()
        self._relay = False
        self._pulse_until: float | None = None
        self._next_pulse_s: float | None = None
        self._register = 0.0
        self._vin: float | None = None

    # -- lifecycle ---------------------------------------------------------------

    def open(self) -> None:
        """Try to open the board; on failure, retry from :meth:`step`."""
        with self._lock:
            self._try_open(self._clock.monotonic())

    def start(self) -> None:
        """Open the board and start the sampling thread."""
        self.open()
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run, name="equipment-pimoroni-webrelay", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        """Stop the thread, release the relay, and close the board."""
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None
        with self._lock:
            if self._opened:
                try:
                    self.board.close()
                except BoardError as exc:  # pragma: no cover - best effort
                    logger.warning("closing the board failed: %s", exc)
                self._opened = False

    def _run(self) -> None:  # pragma: no cover - timing loop, covered via step()
        while not self._stop.is_set():
            self.step()
            self._stop.wait(self.config.period_s)

    def _try_open(self, now: float) -> None:
        if now < self._next_open_at:
            return
        try:
            self.board.open()
            self.board.write_relay(self._relay)
        except BoardError as exc:
            self._fail(str(exc))
            self._next_open_at = now + self.config.reopen_every_s
            return
        self._opened = True
        self._last_error = ""
        logger.info("board opened: %s", self.board.name)

    def _fail(self, message: str) -> None:
        if message != self._last_error:
            logger.warning("%s", message)
        self._last_error = message

    # -- sampling ----------------------------------------------------------------

    def step(self) -> None:
        """Take one sample, update the counters, and end a pulse that is due."""
        with self._lock:
            now = self._clock.monotonic()
            if not self._opened:
                self._try_open(now)
                if not self._opened:
                    self._last_tick = None
                    return
            self._end_pulse_if_due(now)
            try:
                volts = self.board.read_input_volts()
                self._vin = self.board.read_vin_volts()
            except BoardError as exc:
                self._fail(str(exc))
                self._last_tick = None
                return
            self._last_ok = now
            self._last_error = ""
            if self._input == ON and self._last_tick is not None:
                elapsed = now - self._last_tick
                self._on_time += elapsed
                self._total_on_time += elapsed
            self._last_tick = now
            self._update_input(volts, now)
            self._expire_edges(now)

    def _update_input(self, volts: float, now: float) -> None:
        if volts >= self.config.on_min_v:
            reading: int | None = ON
        elif volts <= self.config.off_max_v:
            reading = OFF
        else:
            reading = None  # between the thresholds: hold
        if reading is None or reading == self._input:
            self._pending = None
            self._pending_count = 0
            return
        if reading != self._pending:
            self._pending = reading
            self._pending_count = 0
        self._pending_count += 1
        if self._pending_count < self.config.debounce_samples:
            return
        previous = self._input
        self._input = reading
        self._pending = None
        self._pending_count = 0
        self.board.set_input_light(reading == ON)
        if reading == ON and previous == OFF:
            self._count += 1
            self._on_time = 0.0
            self._edges.append(now)

    def _expire_edges(self, now: float) -> None:
        horizon = now - self.config.frequency_window_s
        while self._edges and self._edges[0] <= horizon:
            self._edges.popleft()

    # -- relay -------------------------------------------------------------------

    def _set_relay(self, on: bool) -> None:
        self._relay = on
        if self._opened:
            try:
                self.board.write_relay(on)
            except BoardError as exc:
                # Reopen on the next step, which writes the requested state again.
                self._fail(str(exc))
                self._opened = False
                self._next_open_at = 0.0

    def _end_pulse_if_due(self, now: float) -> None:
        if self._pulse_until is not None and now >= self._pulse_until:
            self._pulse_until = None
            self._set_relay(False)

    # -- commands ----------------------------------------------------------------

    def apply(self, params: Iterable[tuple[str, str]]) -> None:
        """Apply ``state.json`` control parameters in the order they were sent.

        ``relay1``: 0 off, 1 on, 2 pulse. ``pulseTime1`` overrides the next pulse
        only, so it must come before ``relay1=2``, as on the device. ``onTime1``,
        ``totalOnTime1``, ``count1`` and ``register1`` set their value. Unknown
        names and values out of range are ignored, and the state is returned.
        """
        with self._lock:
            now = self._clock.monotonic()
            for name, value in params:
                self._apply_one(name, value.strip(), now)

    def _apply_one(self, name: str, value: str, now: float) -> None:
        number = _number(value)
        if name == "relay1":
            if value == RELAY_OFF:
                self._pulse_until = None
                self._set_relay(False)
            elif value == RELAY_ON:
                self._pulse_until = None
                self._set_relay(True)
            elif value == RELAY_PULSE:
                seconds = self._next_pulse_s or self.config.pulse_time_s
                self._next_pulse_s = None
                self._pulse_until = now + seconds
                self._set_relay(True)
        elif number is None:
            return
        elif name == "pulseTime1":
            if PULSE_TIME_MIN_S <= number <= PULSE_TIME_MAX_S:
                self._next_pulse_s = number
        elif name == "onTime1":
            self._on_time = max(number, 0.0)
        elif name == "totalOnTime1":
            self._total_on_time = max(number, 0.0)
        elif name == "count1":
            self._count = number
        elif name == "register1":
            self._register = number

    # -- reading -----------------------------------------------------------------

    def healthy(self) -> bool:
        """True when the board is open and the last good sample is fresh."""
        now = self._clock.monotonic()
        return (
            self._opened
            and self._last_ok is not None
            and now - self._last_ok <= self.config.stale_after_s
        )

    def state(self, utc_time: int) -> dict[str, str]:
        """Return the ``state.json`` body, every value a string.

        ``digitalInput1`` is ``"1"`` with voltage applied and ``"0"`` without. When
        the input is unknown (before the first reading, or while the board is not
        answering) it is the empty string, never ``"-1"``: Knilb's ``assertIn`` is a
        substring test, and ``"1"`` is a substring of ``"-1"``.
        """
        with self._lock:
            healthy = self.healthy()
            known = healthy and self._input != UNKNOWN
            frequency = len(self._edges) / self.config.frequency_window_s
            return {
                "digitalInput1": str(self._input) if known else "",
                "onTime1": format_two(self._on_time),
                "totalOnTime1": format_two(self._total_on_time),
                "count1": format_two(self._count),
                "frequency1": format_two(frequency if healthy else 0.0),
                "relay1": RELAY_ON if self._relay else RELAY_OFF,
                "register1": format_register(self._register),
                "vin": f"{self._vin:.1f}" if healthy and self._vin is not None else "",
                "utcTime": str(utc_time),
                "timezoneOffset": str(self.config.timezone_offset_s),
                "serialNumber": self.config.serial_number,
            }

    @property
    def last_error(self) -> str:
        """The most recent board error, or empty when all is well."""
        with self._lock:
            return self._last_error
