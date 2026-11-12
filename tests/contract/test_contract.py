"""The service implements every parameter and field of the committed contract."""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator
from openapi_spec_validator import validate

from equipment_pimoroni_webrelay.api import load_contract
from equipment_pimoroni_webrelay.board import FakeBoard
from equipment_pimoroni_webrelay.clock import FakeClock
from equipment_pimoroni_webrelay.device import Device
from tests.conftest import ON_V, settle


def contract() -> dict[str, Any]:
    return load_contract()


def test_contract_is_valid_openapi() -> None:
    document = contract()
    validate(document)
    assert list(document["paths"]) == ["/state.json"]


def test_every_query_parameter_is_handled(
    client: TestClient, board: FakeBoard, device: Device, clock: FakeClock
) -> None:
    operation = contract()["paths"]["/state.json"]["get"]
    names = [p["name"] for p in operation["parameters"]]
    assert names == [
        "relay1",
        "pulseTime1",
        "onTime1",
        "totalOnTime1",
        "count1",
        "register1",
    ]
    values = {
        "relay1": "1",
        "pulseTime1": "5",
        "onTime1": "7",
        "totalOnTime1": "9",
        "count1": "200",
        "register1": "10.5",
    }
    body = client.get("/state.json", params=values).json()
    assert (body["relay1"], body["onTime1"], body["totalOnTime1"]) == (
        "1",
        "7.00",
        "9.00",
    )
    assert (body["count1"], body["register1"]) == ("200.00", "10.5")


def test_every_property_is_reported(client: TestClient) -> None:
    schema = contract()["components"]["schemas"]["DeviceState"]
    body = client.get("/state.json").json()
    assert set(body) == set(schema["properties"])
    assert set(schema["required"]) <= set(body)


def test_known_bodies_validate(
    client: TestClient, board: FakeBoard, clock: FakeClock
) -> None:
    from tests.conftest import ManualDevice

    schema = contract()["components"]["schemas"]["DeviceState"]
    validator = Draft202012Validator({**schema, "additionalProperties": False})
    app_device: ManualDevice = client.app.state.device  # type: ignore[attr-defined]
    settle(app_device, clock)
    validator.validate(client.get("/state.json").json())
    board.input_volts = ON_V
    settle(app_device, clock)
    validator.validate(client.get("/state.json?relay1=1").json())
