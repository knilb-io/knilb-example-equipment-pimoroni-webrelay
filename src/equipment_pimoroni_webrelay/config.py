"""Settings, read from the environment, ``--env-file`` and ``./.env``.

Settings come from the process environment, ``--env-file`` and ``./.env`` (in that
order of precedence), then defaults. Empty values count as unset.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path

from dotenv import dotenv_values
from pydantic import BaseModel, ConfigDict, Field, model_validator

RELAY_CHANNEL = 1
"""Automation HAT relay driven as ``relay1``."""

PREFIX = "EQUIPMENT_PIMORONI_WEBRELAY_"

ENV_VARS: dict[str, str] = {
    f"{PREFIX}{name.upper()}": name
    for name in (
        "host",
        "port",
        "log_level",
        "password",
        "pulse_time_s",
        "timezone_offset_s",
        "serial_number",
        "input_channel",
        "vin_channel",
        "sample_period_ms",
        "on_min_v",
        "off_max_v",
        "debounce_samples",
        "frequency_window_s",
        "fake",
        "fake_volts",
        "fake_vin",
        "fake_toggle_s",
    )
}


class Settings(BaseModel):
    """Validated configuration."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    host: str = "0.0.0.0"  # binds the bench LAN by design
    port: int = Field(default=80, ge=1, le=65535)
    log_level: str = "INFO"
    password: str = ""
    pulse_time_s: float = Field(default=1.5, ge=0.1, le=86_400)
    timezone_offset_s: int = Field(default=0, ge=-86_400, le=86_400)
    serial_number: str = ""
    input_channel: int = Field(default=1, ge=1, le=3)
    vin_channel: int = Field(default=0, ge=0, le=3)
    sample_period_ms: int = Field(default=20, ge=5, le=5_000)
    on_min_v: float = Field(default=4.0, ge=0.0, le=25.85)
    off_max_v: float = Field(default=1.5, ge=0.0, le=25.85)
    debounce_samples: int = Field(default=2, ge=1, le=100)
    frequency_window_s: float = Field(default=1.0, ge=0.1, le=60.0)
    fake: bool = False
    fake_volts: float = Field(default=0.0, ge=0.0, le=25.85)
    fake_vin: float = Field(default=12.0, ge=0.0, le=25.85)
    fake_toggle_s: float = Field(default=0.0, ge=0.0, le=3_600.0)

    @model_validator(mode="after")
    def _check(self) -> Settings:
        if self.on_min_v <= self.off_max_v:
            raise ValueError("on_min_v must be greater than off_max_v")
        if self.vin_channel == self.input_channel:
            raise ValueError(f"vin_channel {self.vin_channel} is the input channel")
        return self


def load_settings(
    env_file: Path | None = None,
    *,
    environ: Mapping[str, str] | None = None,
    cwd: Path | None = None,
) -> Settings:
    """Merge the sources in precedence order and validate.

    Raises:
        FileNotFoundError: ``env_file`` was given but does not exist.
        ValueError: a value fails validation.
    """
    sources: list[Mapping[str, str | None]] = []
    local_env = (cwd or Path.cwd()) / ".env"
    if local_env.is_file():
        sources.append(dotenv_values(local_env))
    if env_file is not None:
        if not env_file.is_file():
            raise FileNotFoundError(f"env file not found: {env_file}")
        sources.append(dotenv_values(env_file))
    sources.append(os.environ if environ is None else environ)
    data: dict[str, str] = {}
    for source in sources:  # later sources win; empty values count as unset
        data.update({ENV_VARS[k]: v for k, v in source.items() if k in ENV_VARS and v})
    return Settings.model_validate(data)
