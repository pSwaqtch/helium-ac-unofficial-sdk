# Google Assistant integration

Goal: **"Hey Google, turn on AC"** (and set temperature / mode) controls the unit.

There's a native Google Smart Home path (build your own OAuth2 server + SYNC/QUERY/
EXECUTE intent handling) but that's a large effort for one AC. The two practical
routes below both avoid it.

| Route | Cost | Inbound ports | Needs Home Assistant | Best for |
|---|---|---|---|---|
| **SinricPro bridge** | Free (≤3 devices) | **None** (outbound ws) | No | This VPS deployment — recommended |
| Home Assistant | Free\* | Yes, or Nabu Casa (~$6.50/mo) | Yes | If you already run HA / want a dashboard |

\* Free HA→Google needs a Google Cloud project + your own HTTPS endpoint; Nabu Casa
removes that for a subscription.

---

## Recommended: SinricPro bridge

SinricPro publishes a free, maintained Google Home (and Alexa) integration. A small
bridge process holds an **outbound** websocket to their cloud, receives the voice
commands, and sends this project's `cloud` (AWS IoT MQTT) payloads to the AC.

```
"Hey Google…" → Google Home → SinricPro cloud → bridge → AWS IoT → AC
```

Why this is the fit for the cloud/VPS deployment:

* **No inbound exposure.** The bridge only dials out, so no firewall/security-list
  changes and nothing new reachable from the internet.
* **No extra services.** No Home Assistant, no reverse proxy, no OAuth server.
* **Native device in Google Home.** Shows up as a real thermostat, so on/off,
  setpoint and mode "just work" by voice.

Only the `cloud` transport is used — a cloud host has no Bluetooth radio near the
unit. That does mean you depend on Helium's AWS IoT staying up (same caveat as any
cloud control).

**Setup and running: [`bridge/README.md`](../bridge/README.md).** In short: create a
free `Thermostat` device at <https://sinric.pro>, put its App Key / App Secret /
Device Id in `.env`, run `bridge/sinricpro_bridge.py` as a user systemd service,
and link "Sinric Pro" in the Google Home app.

### Limits

* Indoor temperature **is** reported to Google (room-temp DP, refreshed periodically
  and on every command); humidity shows 0% (the AC has no humidity sensor).
* Power/setpoint *displayed* state reflects the last command the bridge sent, not a
  live read — the device's cloud state dump is intermittent by design (see main README).
* Relative temperature ("make it cooler") isn't wired; use absolute ("set AC to 23").
* Fan / swing / turbo aren't exposed yet — see below.

### Future: more controls

The Thermostat device covers power, setpoint and cool/heat mode. The AC's other
capabilities can be added too. The clean way in Google Home is **one extra
SinricPro device per control** (Google's voice handling for a device's custom
sub-controls is unreliable; separate devices "just work"). Each new device is
created in the SinricPro portal, its Device Id added to `.env`, and wired into
`bridge/sinricpro_bridge.py`.

| Add as SinricPro… | Voice | Helium command | Notes on cloud |
|---|---|---|---|
| **Fan** ("AC Fan") | "set AC Fan to high/medium/low" | `fan` (auto/low/med/high) | Sends fine; reads back "unknown" over cloud |
| **Switch** "AC Turbo" | "turn on AC turbo" | `turbo` | ⚠️ unit acts **inverted**, no state echo |
| **Switch** "AC Swing" | "turn on AC swing" | `verticalSwing` | ⚠️ inverted, no echo |
| **Switch** "AC Sleep" | "turn on AC sleep" | `sleep` | fire-and-forget, no echo |
| **Switch** "AC Display" | "turn on AC display" | `display` | fire-and-forget, no echo |
| Switch "AC Silent" / "AC H-Swing" | … | `silent` / `horizontalSwing` | least-tested |

Two caveats, both inherent to the hardware (not the bridge), documented in the
main README and `PROTOCOL.md §7l`:

* **The airflow toggles are inverted** — the unit acts on a byte-identical payload
  backwards (confirmed for turbo and vertical swing). "Turn on turbo" may leave it
  off. The bridge could invert them to compensate, but that's per-toggle guesswork
  without watching the unit.
* **No state feedback over cloud** for these — Google shows the last command sent,
  since the AC only echoes setpoint and room temp reliably on cloud.

Best next addition is the **Fan** device: genuinely useful and it behaves normally.
The on/off toggles work but are the flaky/inverted ones — add them only if wanted.
(All of these remain available meanwhile via the web panel and HTTP API.)

---

## Alternative: Home Assistant

Use this if you already run Home Assistant or want its dashboard/automations. HA
talks to the Helium API (`web/server.py`, default port **5055**) over REST and has
built-in Google Assistant bridging (Nabu Casa for one-click, or the free manual
[Google Assistant integration](https://www.home-assistant.io/integrations/google_assistant/)).

On the same-VPS "zero hardware" setup, run HA (e.g. in Docker) alongside this
project and point it at `http://localhost:5055`. On the VPS use `transport=cloud`
(no Bluetooth); a local HA on hardware in range can use `transport=ble`.

> **These snippets are corrected against the real API.** Two things the API does
> that a first guess gets wrong:
> 1. **Booleans, not strings.** `POST /api/ac/command` runs `bool(value)`. In
>    Python `bool("off")` is `True`, so `{"power":"off"}` would turn it **on**.
>    Send JSON `true` / `false`.
> 2. **State is nested and uses raw DP names.** `GET /api/ac/state` returns
>    `{"transport":…, "state":{"power":1, "setpoint_C":24, "room_temp_C":27,
>    "power_W":850}}` — not `temperature`/`room`/`mode` at the top level. Over
>    `cloud`, `power`/`mode`/`fan` are often absent (device doesn't answer);
>    `setpoint_C` and `room_temp_C` are the reliable ones.

### REST commands (actions)

```yaml
rest_command:
  helium_ac_power_on:
    url: "http://localhost:5055/api/ac/command?transport=cloud"
    method: POST
    headers: { content-type: "application/json" }
    payload: '{"power": true}'

  helium_ac_power_off:
    url: "http://localhost:5055/api/ac/command?transport=cloud"
    method: POST
    headers: { content-type: "application/json" }
    payload: '{"power": false}'

  helium_ac_set_temp:
    url: "http://localhost:5055/api/ac/command?transport=cloud"
    method: POST
    headers: { content-type: "application/json" }
    payload: '{"temperature": {{ temperature }}}'   # 16–30
```

### REST sensor (state)

```yaml
sensor:
  - platform: rest
    name: "Helium AC"
    resource: "http://localhost:5055/api/ac/state?transport=cloud"
    scan_interval: 120          # a cloud read spins up a fresh MQTT connect + retries; keep it slow
    value_template: >
      {{ 'on' if value_json.state.power == 1 else 'off' }}
    json_attributes_path: "$.state"
    json_attributes:
      - setpoint_C
      - room_temp_C
      - power_W
```

### Exposing to Google

Build a script or `climate` entity from the above, then either enable Nabu Casa
(Settings → Voice Assistants → Google Assistant) or follow the free manual guide
linked above.
