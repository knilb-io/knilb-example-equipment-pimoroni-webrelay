from __future__ import annotations

import io
from pathlib import Path
from typing import Any

import pytest
import yaml

from equipment_pimoroni_webrelay import __version__
from equipment_pimoroni_webrelay.cli import main


def test_version() -> None:
    out = io.StringIO()
    assert main(["version"], out=out) == 0
    assert out.getvalue().strip() == __version__


def test_contract_to_stdout_and_file(tmp_path: Path) -> None:
    out = io.StringIO()
    assert main(["contract"], out=out) == 0
    assert "/state.json" in yaml.safe_load(out.getvalue())["paths"]
    target = tmp_path / "webrelay-openapi.yaml"
    assert main(["contract", "-o", str(target)]) == 0
    assert "/state.json" in yaml.safe_load(target.read_text())["paths"]


def test_serve_passes_overrides() -> None:
    calls: list[dict[str, Any]] = []

    def run(app: Any, **kwargs: Any) -> None:
        calls.append({"app": app, **kwargs})

    argv = ["serve", "--fake", "--port", "8080", "--host", "127.0.0.1"]
    assert main([*argv, "--fake-toggle-s", "2"], run_server=run) == 0
    call = calls[0]
    assert (call["host"], call["port"], call["workers"]) == ("127.0.0.1", 8080, 1)
    settings = call["app"].state.settings
    assert settings.fake is True
    assert settings.fake_toggle_s == 2


def test_bad_settings_exit_2(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("EQUIPMENT_PIMORONI_WEBRELAY_PORT", "0")
    assert main(["serve", "--fake"], run_server=lambda *a, **k: None) == 2
    assert "equipment-pimoroni-webrelay:" in capsys.readouterr().err
