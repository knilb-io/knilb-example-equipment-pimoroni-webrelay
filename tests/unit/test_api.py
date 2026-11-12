from __future__ import annotations

import base64
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from equipment_pimoroni_webrelay.api import (
    authorized,
    build_board,
    build_device,
    serial_number,
)
from equipment_pimoroni_webrelay.board import AutomationHatBoard, FakeBoard
from equipment_pimoroni_webrelay.clock import FakeClock
from equipment_pimoroni_webrelay.config import Settings
from tests.conftest import ON_V, ManualDevice, make_client, settle

FIELDS = {
    "digitalInput1",
    "onTime1",
    "totalOnTime1",
    "count1",
    "frequency1",
    "relay1",
    "register1",
    "vin",
    "utcTime",
    "timezoneOffset",
    "serialNumber",
}


def basic(user: str, password: str) -> str:
    return "Basic " + base64.b64encode(f"{user}:{password}".encode()).decode()


def test_read(client: TestClient, manual: ManualDevice, clock: FakeClock) -> None:
    settle(manual, clock)
    response = client.get("/state.json")
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/json"
    body = response.json()
    assert set(body) == FIELDS
    assert all(isinstance(value, str) for value in body.values())
    assert body["digitalInput1"] == "0"
    assert body["utcTime"].isdigit()


def test_control_in_query_order(
    client: TestClient, board: FakeBoard, manual: ManualDevice, clock: FakeClock
) -> None:
    body = client.get("/state.json?pulseTime1=5&relay1=2&register1=10.5").json()
    assert body["relay1"] == "1"
    assert body["register1"] == "10.5"
    clock.advance(5.1)
    manual.step()
    assert client.get("/state.json").json()["relay1"] == "0"


def test_input_follows_the_wire(
    client: TestClient, board: FakeBoard, manual: ManualDevice, clock: FakeClock
) -> None:
    settle(manual, clock)
    board.input_volts = ON_V
    settle(manual, clock)
    body = client.get("/state.json").json()
    assert (body["digitalInput1"], body["count1"]) == ("1", "1.00")


@pytest.fixture
def locked(manual: ManualDevice) -> Iterator[TestClient]:
    yield from make_client(manual, password="webrelay")


def test_password_required_when_set(locked: TestClient) -> None:
    response = locked.get("/state.json")
    assert response.status_code == 401
    assert response.headers["www-authenticate"].startswith("Basic")
    wrong = locked.get("/state.json", headers={"Authorization": basic("none", "x")})
    assert wrong.status_code == 401
    ok = locked.get("/state.json", headers={"Authorization": basic("none", "webrelay")})
    assert ok.status_code == 200


@pytest.mark.parametrize(
    "header",
    [None, "Bearer abc", "Basic !!!", "Basic " + base64.b64encode(b"\xff").decode()],
)
def test_bad_credentials(header: str | None) -> None:
    assert authorized(header, "webrelay") is False


def test_credentials_without_a_colon() -> None:
    assert authorized("Basic " + base64.b64encode(b"webrelay").decode(), "x") is False


def test_no_password_allows_everyone() -> None:
    assert authorized(None, "") is True


def test_contract_is_served(client: TestClient) -> None:
    document = client.get("/openapi.json").json()
    assert "/state.json" in document["paths"]
    text = client.get("/openapi.yaml").text
    assert "state.json" in text


def test_build_board(tmp_path: Path) -> None:
    assert isinstance(build_board(Settings(fake=True)), FakeBoard)
    assert isinstance(build_board(Settings()), AutomationHatBoard)
    device = build_device(Settings(fake=True, serial_number="AA"))
    assert device.config.serial_number == "AA"


def test_serial_number_from_the_mac(tmp_path: Path) -> None:
    address = tmp_path / "address"
    address.write_text("b8:27:eb:12:34:56\n", encoding="ascii")
    assert serial_number(Settings(), address) == "B8:27:EB:12:34:56"
    address.write_text("", encoding="ascii")
    assert serial_number(Settings(), address) == "00:00:00:00:00:00"
    assert serial_number(Settings(), tmp_path / "missing") == "00:00:00:00:00:00"
