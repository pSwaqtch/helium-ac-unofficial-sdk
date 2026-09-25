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
  (DP `0x6A`, plain °C) from the datapoint dumps the AC pushes to its ack topic,
  and forwards it to Google on change, at most every `TEMP_INTERVAL_SEC` (300s). A
  reading older than `STALE_SEC` (900s) is not reported at all — the AC stops
  publishing once it is off the cloud, and a stale number is worse than none. The
  AC exposes no humidity, so humidity is reported as 0%.
- **Commands fail honestly when the AC is off the cloud.** The cloud path is QoS-0
  with no device ack, so a publish "succeeds" locally whether or not the unit is
  attached to hear it. Rather than assume, the bridge **asks**: after
  `OFFLINE_AFTER_SEC` (15min) of silence on the ack topic it prods the unit, and if
  the prod goes unanswered for `ANSWER_GRACE_SEC` (60s) it marks the AC unreachable
  and **refuses** commands. Google then reports a failure instead of flipping the
  tile over a unit that never moved.

  Asking is necessary because **a silent AC is not a dead AC** — measured, after
  two cheaper designs turned out wrong:

  | Test | Verdict |
  |---|---|
  | "quiet for 120s ⇒ offline" | **Wrong.** The unit publishes a burst of ~7 dumps 6s apart, then sleeps for many minutes. 9min of silence observed on a unit running at 272W that answered the next prod in 21.5s. Fleet-wide, a quarter of units send ≤2 messages in any 150s window. |
  | "no answer within 8s of a command ⇒ offline" | **Wrong.** The same prod was answered after 8s, 21.5s and ~25s on three tries. |
  | "no answer 60s after a prod ⇒ offline" | Sound. The outage this was written for answered nothing for two days. |

  The trade is deliberate: a working unit is never refused, at the cost of the
  commands sent before an outage is established still reporting success.
- **The prod, and how to turn it off.** It re-sends *the setpoint the unit itself
  last reported* — byte-identical to what the vendor app sends, a no-op for the MCU
  (verified: the unit was still at 26 °C after two of them), and it reliably draws a
  dump. It fires at most every `PROBE_SEC` (180s) and only while the AC stays
  silent, so a live unit sees roughly one prod per 15min; answering it resets the
  clock. Two guards keep it from surprising the hardware: the value must have come
  from the device (never a cached guess that could move your setpoint), and the
  unit must have reported itself **on** — whether a setpoint command wakes an idle
  unit is untested, so while the AC reports itself off nothing is prodded and no
  command is refused. `HELIUM_BRIDGE_PROBE=0` in `.env` stops the bridge publishing
  anything on its own, which also removes its only evidence for refusing — it then
  reports every command as a success, as it did before this was added.
- **The verdict survives a restart.** systemd restarts this process on a dead
  SinricPro socket a couple of times a day, and an outage outlives that easily (the
  original lasted two days), so a forgetful bridge would go straight back to
  reporting false successes. The verdict and the device-reported values the prod
  needs are cached in `~/.cache/helium-sinricpro-state.json`
  (`HELIUM_BRIDGE_STATE` moves it). Only the AC speaking again clears a saved
  "not answering", so a restart cannot launder a dead unit back into looking
  healthy — and a saved setpoint older than an hour is dropped rather than echoed
  at a unit whose setpoint may have moved in the meantime.
- **State flows back both ways.** The unit dumps its datapoints whenever something
  changes — including changes made on the IR remote — so Google follows the AC, not
  just the commands this bridge sent.
- **Relative temperature** ("make it cooler") isn't wired up — use absolute
  ("set AC to 23"). The SDK doesn't hand the bridge a reliable current setpoint to
  offset from over the flaky cloud read.
- **Fan speed is wired, but invisible in Google Home.** It rides SinricPro's Range
  capability (`0`=auto, `1`=low, `2`=medium, `3`=high, matching DP `0x05`), which
  Google Home does not render — it works from the SinricPro app and Alexa. Swing /
  turbo / sleep / display aren't exposed at all; they remain available via the web
  panel and HTTP API.
- The bridge makes only an **outbound** connection — nothing new is exposed to the
  internet.
- **Auto-recovery.** The SinricPro SDK doesn't reconnect and ships keepalive pings
  effectively disabled (a millisecond/second bug), so a dropped websocket would
  otherwise leave the device stuck "not responding". The bridge forces real
  keepalive pings and runs a watchdog that exits on a dead socket, letting systemd
  restart it fresh (`Restart=on-failure`). A couple of such restarts a day is
  normal.

## Troubleshooting

Start with the log:

```bash
journalctl --user-unit helium-sinricpro -f

# the box should stay on UTC; render the journal in your own zone instead:
TZ=Asia/Kolkata journalctl --user-unit helium-sinricpro -f
```

Under systemd the bridge prints no timestamp of its own — journald already stamps
every line, and *its* stamp renders in the reader's timezone, so a `TZ=` prefix is
all it takes (two timestamps 5:30 apart on one line is just confusing). Run the
bridge in a terminal and it timestamps its own lines again.

### "Google said it worked but the AC didn't move"

Look for `AC is not answering (…) — refusing the command`. The unit is not
attached to Helium's AWS IoT, so nothing this bridge publishes can reach it. The
fix is at the AC, not here:

1. Power-cycle the AC at the plug/breaker for ~30s — the Wi-Fi module hangs while
   the unit keeps working from the remote. This is the usual fix.
2. Check the network: SSID/password changed, 2.4GHz band still up, DHCP lease.
3. Re-provision the AC in the vendor Helium app if it still doesn't come back.

The vendor app will be just as dead while this is true, which confirms the unit is
at fault. `AC is answering (dumping its datapoints)` in the log means it is back.

`restored state from N min ago: AC was NOT answering` on startup means the
previous run had already established an outage; it stands until the unit speaks.

Note what is **not** a fault: `AC is answering` followed by many minutes of no log
lines at all, or an occasional `AC silent for 15 min — echoing its own setpoint …`
followed by `AC is answering`. The unit reports in bursts and then sleeps; it still
takes commands in between (verified — silent for 9min, answered the next prod in
21.5s). Only `AC is not answering` means something is actually wrong.

To prove it is your unit and not this project or the vendor cloud: the shipped
`AWSiOT.p12` is a **fleet-wide** cert, so you can compare your AC against every
other Helium unit on the broker.

```bash
.venv/bin/python - <<'EOF'
import ssl, time, helium_cloud as h, paho.mqtt.client as mqtt
certfile, keyfile = h._extract_pem()
cli = mqtt.Client(client_id=h._client_id(), protocol=mqtt.MQTTv311)
cli.tls_set(ca_certs=h.CA_PATH, certfile=certfile, keyfile=keyfile,
            cert_reqs=ssl.CERT_REQUIRED, tls_version=ssl.PROTOCOL_TLS_CLIENT)
mine, total, devices = 0, 0, set()
def on_msg(c, u, m):
    global mine, total
    total += 1
    parts = m.topic.split("/")
    if len(parts) >= 5:
        devices.add(parts[4])
    if h.MAC in m.topic:
        mine += 1
cli.on_connect = lambda c, u, f, rc, *a: c.subscribe("hoags/#", qos=0)
cli.on_message = on_msg
cli.connect(h.HOST, h.PORT, keepalive=60); cli.loop_start()
time.sleep(150)
cli.loop_stop(); cli.disconnect()
print(f"{total} msgs from {len(devices)} devices; ours ({h.MAC}): {mine}")
EOF
```

A healthy fleet with `ours: 0` (seen live: 883 messages from 52 devices, 0 from
ours) means the broker, the cert and the topic path are all fine and the AC itself
is off the cloud. Only topic names are inspected — never other units' payloads.

### Device shows "not responding" in Google or SinricPro

That is the *SinricPro* websocket, not the AC — see **Auto-recovery** above. The
watchdog notices within about a minute and systemd restarts the bridge.
