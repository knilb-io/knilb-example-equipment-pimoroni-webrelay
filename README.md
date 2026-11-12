# knilb-example-equipment-pimoroni-webrelay

> This repository is an example. It shows one way to build test equipment for Knilb on low-cost hardware. It is not a finished product, it is not maintained on a schedule, and it may change or be archived without notice. Fork it and adapt it to your bench.

`equipment-pimoroni-webrelay` turns a Raspberry Pi 3 with a Pimoroni Automation HAT into a stand-in for a single-relay, single-input web relay. It answers the same `GET /state.json` API, described by the OpenAPI document in this repository, so a [Knilb](https://knilb.com) plan written against that API runs unchanged with the Pi cast into the role.

That is the point of the example: in Knilb, a role is a contract. Any instrument that keeps the contract can fill the role, and switching instruments means choosing a different device in the deployment, not rewriting steps or rewiring the device under test.

It is a demonstration, not a copy of the web relay product: it implements the one endpoint the contract declares, with every parameter and field in it.

Contents: [Try it without hardware](#try-it-without-hardware) · [Bench hardware](#bench-hardware) · [Wiring](#wiring) · [Install on the Raspberry Pi](#install-on-the-raspberry-pi) · [Configuration](#configuration) · [API](#api) · [Knilb set-up](#knilb-set-up) · [Limitations](#limitations) · [Development](#development)

## Try it without hardware

The service runs on macOS or Linux with a fake board. Python 3.11 or newer.

```bash
python3 -m venv .venv
.venv/bin/pip install equipment_pimoroni_webrelay-0.1.0-py3-none-any.whl     # or: pip install .
.venv/bin/equipment-pimoroni-webrelay serve --fake --port 8000 --fake-toggle-s 2
```

`--fake` replaces the HAT with a scripted board, and `--fake-toggle-s 2` turns the input on and off every 2 seconds so you can watch `digitalInput1`, `count1` and `onTime1` move. In another terminal:

```bash
curl -s localhost:8000/state.json
curl -s 'localhost:8000/state.json?relay1=1'
curl -s 'localhost:8000/state.json?pulseTime1=3&relay1=2'
```

Interactive API docs, built from the contract, are at <http://localhost:8000/docs>.

## Bench hardware

| Item | Notes |
|---|---|
| Raspberry Pi 3 | Raspberry Pi OS Lite (64-bit is fine), headless, a fixed address on the bench LAN. |
| Pimoroni Automation HAT | Full-size HAT (the pHAT has only one analog input). I2C must be enabled. |
| The signal to watch | A DC voltage between 0 and 24 V, such as a thermostat's fan terminal powered from a DC supply. |

**Why an analog input.** The HAT's buffered digital inputs float when nothing drives them, and the only cure is an external resistor. The analog channels have an on-board 120k/820k divider to ground, so an open contact reads a defined 0 V. The service turns the reading into on or off with hysteresis: on at or above 4.0 V, off at or below 1.5 V, unchanged in between.

## Wiring

| From | To | Note |
|---|---|---|
| Signal + | HAT **ANALOG 1** | `digitalInput1`. 0 to 24 V DC; never more than 24 V. Another channel works too: set `EQUIPMENT_PIMORONI_WEBRELAY_INPUT_CHANNEL` to 2 or 3 |
| Signal - | HAT **GND** | Shared reference with the Pi |
| Supply + (optional) | Another HAT ANALOG channel | `vin`. Set `EQUIPMENT_PIMORONI_WEBRELAY_VIN_CHANNEL` to match |
| Your load | HAT **RELAY 1** COM, NO, NC | `relay1`. 24 V and 2 A at most; check the HAT's ratings for your load |

**The thermostat bench.** To watch a thermostat's fan call, wire its G terminal to ANALOG 1 and its C terminal to GND. Another instrument can watch the same G and C at the same time, which is how the "same role, two instruments" demo runs one plan on either instrument without rewiring. Never connect this to a real HVAC transformer: the thermostat circuit shares ground with the Pi through HAT GND.

**A Pi shared with another HAT service.** When the same Pi and HAT also run another service that already has G on ANALOG 3 (with W and Y on 1 and 2), set `EQUIPMENT_PIMORONI_WEBRELAY_INPUT_CHANNEL=3` and leave the wiring alone. Run only one of the services at a time: each expects to own the HAT, its I2C bus and its LEDs. With systemd, stop and disable one unit before starting the other.

## Install on the Raspberry Pi

1. **Flash the SD card** with Raspberry Pi Imager: Raspberry Pi OS Lite (64-bit), with a username, your network, and SSH turned on. Connect with `ssh <user>@<pi>.local`.
2. **Enable I2C and install build prerequisites:**

   ```bash
   sudo raspi-config nonint do_i2c 0
   sudo apt update && sudo apt install -y python3-venv python3-dev build-essential i2c-tools
   ```

3. **Get the wheel onto the Pi.** Download `equipment_pimoroni_webrelay-<version>-py3-none-any.whl` from this repository's GitHub Releases, then copy it over:

   ```bash
   ssh <user>@<pi>.local 'mkdir -p ~/equipment-pimoroni-webrelay'
   scp equipment_pimoroni_webrelay-0.1.0-py3-none-any.whl <user>@<pi>.local:~/equipment-pimoroni-webrelay/
   ```

4. **Install it** with the `hat` extra, which pulls in Pimoroni's `automationhat` driver:

   ```bash
   cd ~/equipment-pimoroni-webrelay
   python3 -m venv .venv
   .venv/bin/pip install './equipment_pimoroni_webrelay-0.1.0-py3-none-any.whl[hat]'
   ```

5. **Run it by hand** on port 8000, since port 80 needs extra rights:

   ```bash
   ~/equipment-pimoroni-webrelay/.venv/bin/equipment-pimoroni-webrelay serve --port 8000
   curl -s http://<pi>.local:8000/state.json
   ```

6. **Or run it as a service on port 80,** like a web relay. The unit grants only the right to bind port 80:

   ```bash
   sudo cp deploy/equipment-pimoroni-webrelay@.service /etc/systemd/system/
   sudo systemctl enable --now equipment-pimoroni-webrelay@$USER
   curl -s http://localhost/state.json
   ```

   Logs: `journalctl -u equipment-pimoroni-webrelay@$USER -f`.

## Configuration

Settings are read in this order, later sources overriding earlier ones: defaults, `./.env`, the file given by `--env-file`, then the process environment. Empty values count as unset. Every variable is listed with a comment in [`.env.example`](.env.example).

| Variable (prefix `EQUIPMENT_PIMORONI_WEBRELAY_`) | Default | Meaning |
|---|---|---|
| `HOST`, `PORT` | `0.0.0.0`, `80` | Bind address and port |
| `PASSWORD` | empty | HTTP Basic password. Empty means no authentication |
| `PULSE_TIME_S` | `1.5` | Default length of a `relay1=2` pulse |
| `TIMEZONE_OFFSET_S` | `0` | Reported as `timezoneOffset` |
| `SERIAL_NUMBER` | empty | Reported as `serialNumber`; empty reports the Pi's Ethernet MAC |
| `INPUT_CHANNEL` | `1` | ANALOG channel (1, 2 or 3) read as `digitalInput1` |
| `VIN_CHANNEL` | `0` | ANALOG channel for `vin`, other than the input channel; 0 means none |
| `SAMPLE_PERIOD_MS` | `20` | Input sampling period |
| `ON_MIN_V`, `OFF_MAX_V` | `4.0`, `1.5` | Input hysteresis thresholds |
| `DEBOUNCE_SAMPLES` | `2` | Consecutive samples that must agree before the input changes |
| `FREQUENCY_WINDOW_S` | `1.0` | Window for `frequency1` |
| `LOG_LEVEL` | `INFO` | Python log level |
| `FAKE`, `FAKE_VOLTS`, `FAKE_VIN`, `FAKE_TOGGLE_S` | `0`, `0`, `12.0`, `0` | Development only: the fake board |

## API

One endpoint, `GET /state.json`, as described in [`webrelay-openapi.yaml`](src/equipment_pimoroni_webrelay/webrelay-openapi.yaml). The running service serves that document unchanged at `/openapi.yaml` and `/openapi.json`. A request with no parameters is a read; control is the same GET with query parameters, applied in the order sent.

```json
{"digitalInput1": "1", "onTime1": "4.20", "totalOnTime1": "61.35", "count1": "12.00", "frequency1": "0.00", "relay1": "0", "register1": "0", "vin": "12.2", "utcTime": "1794081304", "timezoneOffset": "0", "serialNumber": "B8:27:EB:12:34:56"}
```

| Field | Meaning on the Pi |
|---|---|
| `digitalInput1` | The input channel (ANALOG 1 by default): `"1"` with voltage applied, `"0"` without, `""` when unknown (before the first reading, or while the HAT isn't answering) |
| `onTime1` | Seconds the input has been on since it last came on; held while it is off |
| `totalOnTime1` | Total seconds the input has been on |
| `count1` | Off-to-on transitions of the input |
| `frequency1` | Off-to-on transitions per second over the last `FREQUENCY_WINDOW_S` |
| `relay1` | `"1"` while RELAY 1 is energized, else `"0"` |
| `register1` | The value last set with `register1=` |
| `vin` | The voltage on `VIN_CHANNEL`, one decimal; `""` when none is wired |
| `utcTime`, `timezoneOffset`, `serialNumber` | The Pi's clock, the configured offset, and the configured serial or the Ethernet MAC |

| Parameter | Effect |
|---|---|
| `relay1=0`, `1`, `2` | Off, on, or a pulse. On or off cancels a pulse in progress |
| `pulseTime1=<s>` | Overrides the length of the next pulse only, 0.1 to 86400 s. It must come before `relay1=2` |
| `onTime1=`, `totalOnTime1=`, `count1=` | Set that counter, usually to 0 |
| `register1=<n>` | Set the register |

Unknown parameters and values out of range are ignored, and the state is returned. With `PASSWORD` set, a request without the right Basic credentials gets `401`; any username is accepted.

**Why `""` and not `"-1"` for unknown.** Knilb's `assertIn` is a substring test, and `"1"` is inside `"-1"`, so `-1` would pass a check that the input is on. An empty string fails both `assertIn "0"` and `assertIn "1"`.

## Knilb set-up

1. If your account doesn't have the web relay spec yet, import [`webrelay-openapi.yaml`](src/equipment_pimoroni_webrelay/webrelay-openapi.yaml) (or `curl -s http://<pi>/openapi.yaml -o webrelay-openapi.yaml`). An existing copy of the same document works as is.
2. Register the Pi as a device: type **ATE**, URL `http://<pi-ip>` (or `http://<pi-ip>:8000` when running by hand), exact with no trailing slash, and add the web relay spec to it.
3. In the deployment of a plan whose role uses that spec, cast the role to the Pi instead of the web relay, and work the deployment to Ready. The plan, its cases and its steps don't change.

## Limitations

- One input and one relay, as the contract describes. The HAT's other channels and relays are not used, except an optional `vin` channel.
- The input is sensed through the 0-24 V analog channel, so it needs a DC signal. An AC signal reads as a rectified wave and can chatter.
- No HTTPS, no `state.xml`, and nothing else the contract doesn't declare.
- Bench LAN only. With no password set, anyone on the network can drive the relay.

## Development

```bash
pipenv install --dev
make check     # ruff, mypy --strict, pytest with branch coverage >= 90%
make wheel     # build dist/
```

The tests run against the fake board and a fake clock; nothing needs a Raspberry Pi. The contract tests check that every parameter and response field in `webrelay-openapi.yaml` is implemented and that responses validate against it.

## License

MIT. See [LICENSE](LICENSE).
