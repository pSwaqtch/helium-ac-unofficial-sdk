# Google Assistant control via SinricPro

Say **"Hey Google, turn on AC"** and this bridge relays it to the unit — no Nabu
Casa fee, no Home Assistant, and **no inbound port opened** on the VPS. SinricPro
provides the free Google Home / Alexa integration; the bridge holds an *outbound*
websocket to their cloud and translates each command into this project's `cloud`
(AWS IoT MQTT) payloads.

```
"Hey Google…" → Google Home → SinricPro cloud → sinricpro_bridge.py → AWS IoT → AC
```

Only the `cloud` transport is used (this VPS has no Bluetooth near the unit).

## Prerequisites

- The project's `cloud` path already works — `.env` has `HELIUM_DEVICE_MAC`, and
  `apk/assets/AWSiOT.p12` + `AmazonRootCA1.pem` are present. Verify:
  ```bash
  .venv/bin/python -c "import helium_cloud as h; c=h.connect(); print('AWS IoT OK'); c.disconnect()"
  ```
- Deps installed in the repo venv:
  ```bash
  .venv/bin/pip install -r bridge/requirements.txt
  ```

## 1. Create the SinricPro device

1. Sign up (free): <https://sinric.pro>.
2. **Credentials** → copy your **App Key** and **App Secret**.
3. **Devices → Add Device**:
   - **Device Type:** `Thermostat`
   - **Name:** `AC`  (this is what you'll say — "turn on **AC**")
   - Save, then copy the generated **Device Id** (24 hex chars).

## 2. Fill in `.env`

Add to the project's `.env` (repo root):

```
SINRICPRO_APP_KEY=xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
SINRICPRO_APP_SECRET=xxxxxxxx-....-longsecret
SINRICPRO_AC_DEVICE_ID=aaaaaaaaaaaaaaaaaaaaaaaa
```

## 3. Test it by hand

```bash
.venv/bin/python bridge/sinricpro_bridge.py
```

You should see `bridge up …`. In the SinricPro web console, toggle the device's
power — the log prints `power -> On` and the AC should respond. Ctrl-C to stop.

## 4. Run it as a service

Install it as a **user** service (not a system unit) — this box has SELinux
enforcing, and a system service runs as `init_t`, which SELinux forbids from
executing binaries under `/home` (`status=203/EXEC`). A user service runs in your
unconfined session and can access the venv in your home dir; `enable-linger` makes
it start at boot without a login.

```bash
mkdir -p ~/.config/systemd/user
cp bridge/helium-sinricpro.service ~/.config/systemd/user/
loginctl enable-linger "$USER"
systemctl --user daemon-reload
systemctl --user enable --now helium-sinricpro
systemctl --user status helium-sinricpro

# live logs (user-unit logs go to the system journal):
sudo journalctl _SYSTEMD_USER_UNIT=helium-sinricpro.service -f
```

## 5. Link to Google

Google Home app → **+ Add → Works with Google → "Sinric Pro"** → sign in with
your SinricPro account. Your `AC` device appears; assign it a room if you like.

Then:
- "Hey Google, **turn on AC**" / "**turn off AC**"
- "Hey Google, **set AC to 24 degrees**"
- "Hey Google, **set AC to cool**" (or heat)

## What maps to what

| You say | SinricPro | AC command |
|---|---|---|
| turn on / off AC | `setPowerState` On/Off | `power_payload` |
| set AC to N degrees | `targetTemperature` | `temperature_payload` (clamped 16–30) |
| set AC to cool / heat | `setThermostatMode` COOL/HEAT | power on + `mode_payload` |
| (mode) off | `setThermostatMode` OFF | power off |

## Notes & limits

- **Indoor temperature is reported.** The bridge reads the unit's room temp
  (DP `0x6A`, plain °C) — from every command ACK and from a periodic non-actuating
  read (`REFRESH_SEC`, default 180s) — and pushes it to Google (`REPORT_SEC`,
  default 60s). The AC exposes no humidity, so humidity is reported as 0%.
- **Fire-and-forget commands.** The cloud path is QoS-0 with no reliable device
  ack, so the bridge reports command success optimistically; Google's power/setpoint
  reflect the last command sent, not a fresh read. (Cloud state reads are
  intermittent by design — see the main README.)
- **Relative temperature** ("make it cooler") isn't wired up — use absolute
  ("set AC to 23"). The SDK doesn't hand the bridge a reliable current setpoint to
  offset from over the flaky cloud read.
- **Fan / swing / turbo etc.** aren't exposed to Google (a thermostat has no such
  controls). They remain available via the web panel and HTTP API.
- The bridge makes only an **outbound** connection — nothing new is exposed to the
  internet.
