from __future__ import annotations

from pathlib import Path

import pytest

from equipment_pimoroni_webrelay.config import Settings, load_settings


def test_defaults() -> None:
    settings = load_settings(environ={})
    assert settings.port == 80
    assert settings.password == ""
    assert settings.pulse_time_s == 1.5


def test_precedence(tmp_path: Path) -> None:
    (tmp_path / ".env").write_text(
        "EQUIPMENT_PIMORONI_WEBRELAY_PORT=8001\nEQUIPMENT_PIMORONI_WEBRELAY_FAKE=1\n"
    )
    extra = tmp_path / "extra.env"
    extra.write_text("EQUIPMENT_PIMORONI_WEBRELAY_PORT=8002\n")
    settings = load_settings(
        extra,
        environ={"EQUIPMENT_PIMORONI_WEBRELAY_PORT": "8003", "UNRELATED": "x"},
        cwd=tmp_path,
    )
    assert settings.port == 8003
    assert settings.fake is True
    blank = load_settings(
        extra, environ={"EQUIPMENT_PIMORONI_WEBRELAY_PORT": ""}, cwd=tmp_path
    )
    assert blank.port == 8002


def test_missing_env_file(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        load_settings(tmp_path / "nope.env", environ={})


def test_thresholds_must_not_overlap() -> None:
    with pytest.raises(ValueError, match="on_min_v"):
        Settings(on_min_v=1.0, off_max_v=2.0)


def test_vin_cannot_share_the_input_channel() -> None:
    with pytest.raises(ValueError, match="vin_channel"):
        Settings(vin_channel=1)
    with pytest.raises(ValueError, match="vin_channel"):
        Settings(input_channel=3, vin_channel=3)


def test_input_channel_from_the_environment() -> None:
    env = {"EQUIPMENT_PIMORONI_WEBRELAY_INPUT_CHANNEL": "3"}
    settings = load_settings(environ=env)
    assert settings.input_channel == 3
    assert Settings(input_channel=3, vin_channel=1).vin_channel == 1


def test_input_channel_range() -> None:
    with pytest.raises(ValueError):
        Settings(input_channel=0)
    with pytest.raises(ValueError):
        Settings(input_channel=4)
