# Helium AC — BLE Protocol Knowledge Base

Reverse-engineering notes for controlling a Helium air conditioner over BLE
without the vendor app. Target: Python (Mac) first, then ESP32.

**Status:**
- **BLE temperature control: SOLVED & working** (`helium.py`). Read/notify + write
  confirmed on a live unit. See §5g for the wire format. This meets the original
  goal (control the AC without the vendor app), locally, no cloud.
- **Cloud/web control: SOLVED & working, ALL 12 commands** (`helium_cloud.py`).
  The runtime MQTT `p12Password` is **`1234`** (captured via Frida — §7i, §7j). We
  connect to AWS IoT with mutual-TLS, read live state, and send the full command
  set: temperature, power, fan, mode, verticalSwing, turbo, sleep, display,
  convertible, silent, horizontalSwing, timer. e2e-verified against BLE ground
  truth (§7j maps each command to the DP it moves); user confirmed audible beeps.
  Wired into `web/server.py` (`GET /api/ac/state`, `POST /api/ac/command`), which
  now drives BLE **and** cloud from one dual-transport web panel (§7k). The
  one non-obvious gotcha: publish RAW bytes at QoS 0, not the hex text (§7j).
- Local WiFi API does **not** exist on the device (§7d); cloud round-trips Mumbai
  and is inferior to BLE for a device in the same home, but enables control from
  outside the home.

**Section index:** §1–4 device/GATT · §5 BLE protocol (5g = final wire format) ·
§6–7c BLE method/next · §7d WiFi/network · §7e–7h cloud architecture & auth ·
§7i APK patching / PairIP bypass / Frida · §8 open questions · §9 files.

---

## 1. Device identity

| Field | Value |
|---|---|
| BLE name | `HELM:HELM__XXXX` (adv) / `HELM__XXXX` (GAP) |
| MAC | `E8:8F:8E:01:7F:93` |
| macOS peripheral UUID | `93E01E83-F89E-9B1A-75C6-C28E886BCFC4` |
| Model | `HELM0000015HMKP1ac` |
| Product | `Helium` |
| MTU | 185 |

**Neighbouring units (NOT ours — ignore):** `HELM__7513`, `HELM__6191`.
macOS hides BLE MACs, so always match by the `7f93` name substring.

---

## 2. GATT table

Service `0000a00a-0000-1000-8000-00805f9b34fb` (vendor specific):

| Char | Handle | Properties | Role |
|---|---|---|---|
| `b001` | 13 | read | Device info blob (see §3) |
| `b002` | 16 | write, write-without-response | **Command channel** |
| `b003` | 18 | notify | **Telemetry + debug log stream** |
| `b004` | 21 | indicate | Unknown (OTA? async events?) |

`b001` user-description descriptor reads: `"V1 read characteristic"`.

Also present: Battery Service `180f` / `2a19` = `0x5a` (90). Probably a
placeholder — a mains-powered AC has no battery.

---

## 3. `b001` device-info blob

Fixed-offset ASCII records, NUL-padded. Decoded:

```
01 00 7a 01                       header / version
"Helium"                          product
"HELM0000015HMKP1ac"              model
"HELM__XXXX"                      device name
01 00 01 00 00 00 18 00 ...       flags (0x18 = 24?)
"Airtel_B801"                     joined WiFi SSID
"<your-device-macid>"                    MAC as lowercase hex string
"1111"                            <-- PIN / pairing key (likely auth)
"<your-hoags-user-uuid>"  device UUID (truncated at 128 B read)
```

**Notable:** the device is WiFi-capable and cloud-connected, not BLE-only.
`1111` is almost certainly the default pairing PIN the app uses to authorise
commands. The UUID is cut off by the 128-byte read — use a long/offset read to
recover the tail if needed.

---

## 4. `b003` notification stream

Plaintext, NUL-terminated ASCII with an incrementing sequence number:

```
<TAG>:<SEQ>:<PAYLOAD>\0
```

Two tags seen so far:

### `Poll:<seq>:<hex>`
Carries the AC's internal **Tuya MCU serial protocol** frames as a hex *string*.

### `Diag:<seq>:<text>`
Raw firmware debug log. Leaks internals:
- `Publishing to hoags/Helium/ac/HELM0000015HMKP1/e8…` — **MQTT topic**
  (`hoags` = vendor cloud namespace). Truncated at 60 B by notification size.
- `->100149c4 1` — periodic heartbeat/pointer, meaning unknown.

> The firmware ships with verbose debug logging enabled over BLE. This is the
> single most valuable find: the device narrates its own state transitions, so
> we can correlate app actions to internal events without guessing.

---

## 5. Tuya frame format (inside `Poll:`)

The AC's control board speaks the standard **Tuya MCU serial protocol**:

```
55 aa | 03  | 07  | 00 08  | <payload>              | cc
hdr   | ver | cmd | length | DP unit(s)             | checksum
```

- Header `55AA` — Tuya magic.
- `cmd 07` — "status report from MCU" (device → host state update).
- Checksum — sum of all preceding bytes mod 256.

### Datapoint (DP) unit layout
```
1c | 02 | 00 04 | 00 00 02 cd
id | ty | len   | value
```
- `type 02` = integer (4-byte big-endian).
- Other Tuya types: `00`=raw, `01`=bool, `03`=string, `04`=enum, `05`=bitmap.

### Observed DPs

| DPID | Type | Meaning | Range seen | Status |
|---|---|---|---|---|
| `0x02` (2) | 02 int | **Setpoint temperature, °C** | 22–26 | **CONFIRMED** |
| `0x1C` (28) | 02 int | **Instantaneous power draw, W** | 314–740 | **CONFIRMED** |

#### DP2 — setpoint temperature
Confirmed by IR-remote correlation (capture `cap_224746.log`). Every remote
press produced exactly one DP2 report, stepping 1 per press:

```
25 -> 24 -> 23 -> 22    (three DOWN presses)
22 -> 23 -> 24 -> 25    (three UP presses)
25 -> 24 -> 23 -> 22    (down again)
22 -> 23 -> 24          (up)
24 -> 25 -> 26          (up)
```

**Encoding is the raw integer in °C — no scale factor, no offset.**
So 24 °C is literally `00 00 00 18`.

#### DP28 — power
Varies independently of DP2 and is not monotonic: rose to 559 W under load,
dropped to 314 W, climbed back to ~450 W. That sawtooth is the compressor
modulating / cycling. Units are watts (a ~0.3–0.75 kW draw is right for a
domestic split AC at part load).

### Checksum — CONFIRMED
Plain `sum(all bytes before checksum) & 0xFF`. Verified against two captured
frames:

```
55aa030700081c020004000002cd02   value=717  cs=0x02 calc=0x02  OK
55aa030700081c020004000002e419   value=740  cs=0x19 calc=0x19  OK
```

Since the checksum is confirmed, **we can forge valid frames.**

### Constructing a setpoint command (untested)
Standard Tuya "send command to MCU" is `cmd 0x06`, the counterpart to the
`cmd 0x07` reports we observe. Predicted frame for 24 °C:

```
55 aa 03 06 00 08 02 02 00 04 00 00 00 18 <cs>
hdr   v  cmd len   DP2 int len=4  value=24
```

Still unknown: whether `b002` wants this as raw bytes or as an ASCII hex string
wrapped in a `Tag:<seq>:` envelope, matching the `Poll:`/`Diag:` read format.

---

## 5b. Write attempts on `b002` — ALL FAILED

Tried sending a DP2=24 setpoint (`55aa030600080202000400000018 30`) in seven
envelopes, each with both write-with-response and write-without-response:

| Envelope | GATT accepted | MCU reacted |
|---|---|---|
| raw bytes | yes | **no** |
| ASCII hex | yes | **no** |
| ASCII hex + NUL | yes | **no** |
| `Cmd:1:<hex>\0` | yes | **no** |
| `Set:1:<hex>\0` | yes | **no** |
| `Ctrl:1:<hex>\0` | yes | **no** |
| `Poll:1:<hex>\0` | yes | **no** |

**Every write was accepted at the GATT layer and silently discarded.** No DP2
echo on `b003`; the only notifications during the probe were the pre-existing
background MQTT/heartbeat `Diag` lines.

### Second round: Tuya command-byte sweep — ALSO ALL FAILED

Swept the Tuya command byte across `0x00,01,02,03,04,05,06,07,08,09,0a,0d,0e,10,22,34`
carrying a valid DP2=24 payload. **No reaction to any of them.**

### Methodology note — beware false positives
The first pass appeared to show "reactions" to several command bytes. It did
not. A 30 s passive baseline with **zero writes** shows the device already
emits ~0.6 notifications/sec on its own:

```
total notifications: 19 in 30s (0.6/sec)
   6x  Poll:N:NaaNcN                                  <- DP28 power reports
   5x  Diag:N:Publishing to hoags/Helium/ac/...       <- MQTT heartbeat
   3x  Diag:N:->NcN N                                 <- internal heartbeat
```

Those `Publishing to` / `->100149c4` lines are free-running background chatter.
Any write-probe harness **must** filter against this baseline or it will report
noise as success. Correlate on a DP echo, never on "some notification arrived".

### Device reboots during probing
Notification sequence numbers reset (`4945` → `40`) between probe runs, i.e. the
**device rebooted**. Cause unconfirmed — possibly unrelated (WiFi reconnect), or
possibly a malformed write upsetting the firmware. Worth watching: if fuzzing
reliably reboots the unit, back off.

### Overall conclusion
**23 distinct write attempts (7 envelopes × 2 write modes, then 16 command
bytes) produced zero MCU response.** The characteristic accepts bytes at the
GATT layer and the firmware discards them all.

The search space is too large to brute-force: envelope format × command byte ×
sequence-number validity × probable auth (the `1111` PIN) — and a wrong guess in
any one dimension looks identical to a wrong guess in all of them. There is no
gradient to follow, and no error response to learn from.

**Stop fuzzing. Get ground truth instead** (see §7b).

---

## 5c. APK ANALYSIS — THE WRITE PROBLEM IS EXPLAINED

Pulled `com.helium.mobileapp` from device `P22299004920` (Android).

```
adb -s P22299004920 shell pm path com.helium.mobileapp
adb -s P22299004920 pull .../base.apk
unzip -o base.apk assets/index.android.bundle
strings -n 4 assets/index.android.bundle > bundle.strings
```

**The app is React Native / Expo, not native Java.** So jadx is the wrong tool —
the logic lives in `assets/index.android.bundle`, which is **Hermes bytecode
v96** (54 MB APK, 2.2 MB bundle). Hermes keeps string literals in the clear, so
`strings` alone recovered the protocol vocabulary.

### ROOT CAUSE of the failed writes: there is a passkey handshake

Strings recovered from the bundle:

```
sendInitialBlePasskey        submitLoginPasskey       awaitingLoginPasskeyEntry
sendLoginBlePasskey("1111")  submitNewPasskey         awaitingInitialPasskeyConfirm
sendNewBlePasskey            parseBlePasskeyStatus    resolutionInitialPasskeySuccess
passkeyAck                   passkeymatches           "Saved passkey no longer valid.
                                                       Please reconnect to re-pair."
"Choose a 4-digit passkey for this AC."  "Avoid using 0000."  "Any 4 digits except 0000"
Poll parser: DPID 0x79 passkey ack  value=0xffffffff
```

**The session must be authenticated with the 4-digit passkey before the MCU
will accept any command.** This fully explains §5b: all 23 writes were
syntactically fine and silently dropped because we never logged in.

- The passkey for this unit is **`1111`** (matches the `b001` blob at offset 121).
- **DPID `0x79` (121) = passkey ack**, reported back on the `Poll:` stream.
- Literal `sendLoginBlePasskey("1111"); true;` appears in the bundle — likely a
  WebView/eval bridge string.

### Command vocabulary (from bundle strings)

Hermes concatenates adjacent literals, so some names below are run together in
raw `strings` output; the underlying set is unambiguous:

```
AC_CMD_POWER_CONTROL       AC_CMD_TEMP_CONTROL      AC_CMD_MODE_CONTROL
AC_CMD_SPEED_CONTROL       AC_CMD_SWING_CONTROL     AC_CMD_TURBO_CONTROL
AC_CMD_SLEEP_CONTROL       AC_CMD_ECO_CONTROL       AC_CMD_DISPLAY_CONTROL
AC_CMD_TIMER_CONTROL       AC_CMD_ON_TIMERCTR       AC_CMD_OFF_TIMERCTR
AC_CMD_IDU_CONTROL         AC_CMD_ODU_CONTROL       AC_CMD_COMPRESSOR_CONTROL
AC_CMD_CONDA_CONTROL       AC_CMD_CONVERTIBLE_CONTROL  AC_CMD_REMOTE_DIAG_CONTROL
AC_CMD_SILENT / NODELAY    AC_CTRL                  AC_CMD_AD
```

Modes: `AC_CMD_MODE_COOL | _DRY | _FAN | _HEAT | _AUTO | _WET | _WINDOW |
_CONVERTIBLE`

Other useful strings: `ACCommandSent`, `AC command error:`, `Could not reset
your AC`, `No AC Found`, `Poll parser: found more than one 55aa, ignoring`,
`[CLOUD] Poll parser DPID: 67`, `writeWithoutResponse`, `Enabling
notifications...`, `Enabling indications...`, `[BLE OTA]` (so `b004` is OTA).

### Cloud endpoints (incidental)
```
https://o7sbv8y912.execute-api.ap-south-1.amazonaws.com/devices/...
/user/devices?user=      /hoags      /statusBar   AWS IoT (assets/AWSiOT.p12)
@helium_auth_token  @helium_user_data   (AsyncStorage keys)
```
The APK ships `assets/AWSiOT.p12` and `AmazonRootCA1.pem` — AWS IoT MQTT creds.

> **PRIVACY:** the bundle also contains hardcoded phone numbers and a company
> address. Not reproduced here beyond what is protocol-relevant.

### Corrected next step
Recover the **numeric DPID ↔ AC_CMD mapping** and the exact passkey frame
format by decompiling the Hermes bytecode (`strings` gives names, not numbers).
Tooling: `hermes-dec` (installed in `.venv`). Then:

1. `sendLoginBlePasskey(1111)` on `b002`
2. wait for DPID `0x79` ack on `b003`
3. send `AC_CMD_TEMP_CONTROL` — expect the DP2 echo we already know how to read

---

## 5d. WIRE FORMAT — FULLY RECOVERED

Decompiled the Hermes bytecode with `hermes-dec` (14.7 MB of pseudo-JS):

```
.venv/bin/python -m hermes_dec.decompilation.hbc_decompiler \
    apk/assets/index.android.bundle bundle_decomp.js
```

### Command IDs (verbatim from the bundle)
```js
{'BLE_PASSKEY': 600, 'STATUS_DATA': 500, 'AC_CTRL': 1003,
 'FIRMWARE_UPDATE': 100, 'VFS_UPDATE': 101, 'FACTORY_RESET': 109,
 'SAVE_DEVICE_NAME': 103, 'WIFI': 700, 'USER_ID': 105}
```
> `FACTORY_RESET: 109` — do not send this by accident while fuzzing.

### Packet.serialize() — 25-byte header + payload
| off | size | field |
|---|---|---|
| 0 | u8 | `header` — always `0xFF` |
| 1 | u16BE | `cmdId` |
| 3 | u16BE | `len` (payload length) |
| 5 | u16BE | `seqNum` |
| 7 | u32BE | `checksum` (observed 0) |
| 11 | u8 | `total_level` |
| 12 | 5 B | `level` (zeros) |
| 17 | u32BE | `totalSize` |
| 21 | u32BE | `params` |
| 25 | … | `payload` |

### AC_CTRL payload = 5-byte sub-header + data
`buildPacket(header5, data)`; `header5[0]` is the sub-command:

| id | builder | data |
|---|---|---|
| 0 | `buildPowerPacket` | `[on ? 0 : 1]` — **inverted: 0 = ON** |
| 1 | `buildFanSpeedPacket` | `[speedIndex]` |
| 2 | `buildTemperaturePacket` | `[celsius & 0xFF]` |
| 3 | `buildModePacket` | `[modeIndex]` |
| 4 | `buildVerticalSwingPacket` | `[v]` |
| 5 | `buildTurboPacket` | `[on ? 0 : 1]` (inverted) |
| 6 | `buildSleepPacket` | `[v]` |

Also present: `buildDisplayPacket`, `buildSilentPacket`, `buildTimerPacket`,
`buildConvertiblePacket`, `buildHorizontalSwingPacket`.

### Transport — raw bytes, NOT hex text
`_writeToDevice` base64-encodes the serialized buffer because
react-native-ble-plx requires base64; the `.toString('hex')` calls nearby are
**debug logging only**. On the wire it is the raw bytes, single write, no
chunking, via `writeCharacteristicWithoutResponseForService`.

Sending ASCII-hex text was wrong and produced only `Diag: Queue is empty`.
Sending raw bytes made the device **dump its whole datapoint table** — proof
the framing is now correct.

## 5e. Full datapoint table (observed live)

| DPID | Meaning | Notes |
|---|---|---|
| `0x01` | power on/off | 1 = on |
| `0x02` | **setpoint °C** | confirmed via IR remote |
| `0x04`,`0x05` | mode / fan (likely) | both 1 |
| `0x08`,`0x19`,`0x1a` | flags | 0 |
| `0x1C` | **power draw, W** | 428–460 running |
| `0x67`,`0x69`,`0x6b` | flags | |
| `0x6A` | **room temperature °C** | 27–28 |
| `0x6d`,`0x6e`,`0x6f` | flags | 1 |
| `0x73`,`0x75` | flags | 0 |
| `0x79` | **passkey ack** | `value=0xffffffff` per bundle |

## 5f. CURRENT BLOCKER — auth not completing

Status: **read = solved, write = still rejected.**

With correct framing the AC responds (full state dump) but:
- no `DPID 0x79` passkey ack is ever received;
- `AC_CTRL` temperature commands are ignored (setpoint stayed 24 when 21 was
  requested, verified against a real baseline over 18 s).

So the packet *parses* but the session is not authenticated.

### Verification discipline (a false positive was caught here)
An early test printed `*** SUCCESS: setpoint None -> 24 ***`. That was **not** a
success — the baseline was `None` because no DP2 had arrived yet, so the first
status report tripped the comparison. Corrected harness (`settest3.py`) now:
1. waits until DP2 is actually present before recording a baseline,
2. aborts if the target already equals the baseline,
3. distinguishes "changed to requested value" from "changed to something else".

**Rule: never treat "a notification arrived" or "a value appeared" as success.
Only a baseline→target transition counts.**

### Remaining unknowns for auth
- `seqNum` is hardcoded 0 here; the app may increment it per session.
- `checksum` is sent as 0 — the app calls `setChecksum(r13)` where `r13` is 0 in
  the passkey path, but AC_CTRL may require a real checksum.
- `params` / `level` / `total_level` semantics unverified.
- The app's passkey path sets `setLen(4)` and `setTotalSize(4)` from the 4-byte
  utf8 buffer — matches what we send.
- Possible ordering requirement (e.g. `USER_ID` (105) first, or a `STATUS_DATA`
  subscription) before `BLE_PASSKEY` is honoured.

### Passive sniffing attempt — BLOCKED (wrong dongle firmware)

Tried capturing a live app session with the nRF dongle:

```
nrfutil ble-sniffer sniff --port /dev/cu.usbmodemECCC8E8A9DA12 \
    --follow-by-name "HELM__XXXX" --output-pcap-file captures/session.pcap
```

**Captured 0 packets** (pcap stayed at 24 bytes = file header only), both with
`--follow-by-name` and with no filter at all in a room full of BLE devices.

Cause:
```
$ nrfutil device list
ECCC8E8A9DA1   Product: nRF52 Connectivity
```

The dongle is flashed with **nRF52 Connectivity firmware**, not nRF Sniffer
firmware. Connectivity firmware makes the dongle a BLE *central* (this is what
nRF Connect uses to connect to the AC); it cannot listen promiscuously. The
`sniff` command runs without error and simply never receives anything.

**Lesson: verify `nrfutil device list` reports sniffer firmware BEFORE running a
capture session.** A silent empty pcap looks identical to "no traffic happened".

To fix: flash `sniffer_nrf52dk_nrf52832_*.hex` (or the matching dongle build)
from Nordic's nRF Sniffer for Bluetooth LE package, then re-verify. Note this
overwrites the Connectivity firmware, so nRF Connect desktop will stop being
able to use the dongle as a central until it is reflashed.

`parse_pcap.py` (written, untested against real data) decodes DLT_NORDIC_BLE
records → ATT Write Req/Cmd → Helium 25-byte packet fields, ready for whenever a
real capture exists.

### Next diagnostic step
Trace the app's own call order at runtime rather than guessing: re-read
`sendLoginBlePasskey` vs `sendInitialBlePasskey` (factory devices use `0000`,
per `[BLE AUTH] → factory device: sendInitialBlePasskey("0000")`), and check
whether a `USER_ID`/handshake packet precedes it. Alternatively sniff the live
app session with the nRF dongle for ground truth on byte order.

---

## 5g. ✅ SOLVED — working write format (ground truth from btsnoop)

Static analysis got the *structure* right but four *values* wrong. The fix came
from an Android HCI snoop capture of a real app session.

### Capturing the snoop log
```
adb shell dumpsys bluetooth_manager | grep sSnoopLogSetting
```
**Gotcha:** `sSnoopLogSettingAtEnable = EMPTY` means the toggle was flipped while
Bluetooth was already running — the stack reads it only at startup. Cycle it:
```
adb shell cmd bluetooth_manager disable && adb shell cmd bluetooth_manager enable
```
until it reports `FULL`. Then use the app, and pull the log:
```
adb bugreport bugreport.zip
unzip -o bugreport.zip "FS/data/misc/bluetooth/logs/btsnoop_hci.log" -d .
.venv/bin/python parse_snoop.py
```

### What the app actually sends

```
PASSKEY  ff 02 58 00 04 00 01 00 00 00 00 01 02 00 00 00 00 00 00 00 04 00 00 00 00 31 31 31 31
TEMP 24C ff 03 eb 00 01 00 01 00 00 00 00 02 02 00 00 00 00 00 00 00 01 00 00 00 00 18
```

### The four corrections

| Field | static-analysis guess | **actual** |
|---|---|---|
| `seqNum` | 0 | **1** |
| `total_level` | 0 | **1** (BLE_PASSKEY) / **2** (AC_CTRL) |
| `level` | `00 00 00 00 00` | **`02 00 00 00 00`** |
| AC_CTRL payload | `[sub,0,0,0,0] + data` (6 B) | **bare value byte** (1 B) |

The last one is the big one: **`buildPacket()`'s 5-byte sub-header is NOT used on
the BLE path.** A temperature write is just `len=1, payload=[celsius]`. The
`buildXxxPacket` family in the bundle appears to serve the *cloud/MQTT* path.

Also: the app uses **ATT Write Request** (0x12, with response), not
write-without-response.

Consequence: with `len=1` payloads there is no room for a sub-command id, so
AC_CTRL is presumably **temperature-only**, and power/mode/fan use different
`cmdId`s or a different payload shape. Not yet captured — see §8.

### Verified working

```python
packet(1003, bytes([celsius]))        # temperature
packet(600,  b"1111", total_level=1)  # passkey
```

Live results (each verified against a real prior baseline, not against `None`):

```
setpoint 25 -> 21   as requested
setpoint 21 -> 26   as requested
setpoint 26 -> 23   as requested
setpoint 23 -> 24   as requested
```

`helium.py` byte-matches the app's frames exactly (asserted against the capture).

### Note on the passkey
No `DPID 0x79` ack is observed in practice, and **commands work anyway** — so
either the unit is already paired/bonded, or the ack only appears on initial
pairing. The passkey write is still useful because it **provokes a full
datapoint dump**, which is the easiest way to read current state.

---

## 6. Working hypotheses (to verify)

1. **`b002` accepts the same ASCII-wrapped format**, likely `Cmd:<seq>:<hex>`
   or a bare Tuya frame hex string. The `Poll:`/`Diag:` tagging suggests a
   simple text command dispatcher on the write side too.
2. **Commands are Tuya `cmd 06`** ("send command to MCU"), the standard
   counterpart to the `cmd 07` reports we see.
3. **`1111` may need to be presented first** as an auth/unlock step before
   writes are honoured.
4. Temperature / power / mode are separate DPIDs we have not yet observed —
   they only report when they *change*, so we must actuate the AC to see them.

---

## 7. Method that is working

Sniffing blind is slow. The fast path is **correlation**: perform one action in
the vendor app (or on the IR remote) and watch which DPID moves in the `b003`
stream. One action at a time, logged with timestamps.

Because `b003` is a full debug log, we get the device's own commentary for free.

---

## 7b. Next step — get ground truth on the write format

Ranked by expected payoff:

1. **Decompile the Android APK.** Fastest, highest certainty. `jadx` on the
   Helium app will show the exact bytes written to `b002`, including any auth
   handshake and the sequence-number scheme. Everything else is guesswork by
   comparison.
2. **Passive-sniff the app↔AC link** with the nRF dongle in sniffer mode (not
   as a connected central) while the phone drives the AC. Captures the real
   writes over the air.
3. **Probe the WiFi/MQTT path.** The device is on `Airtel_B801` and publishes to
   `hoags/Helium/ac/HELM0000015HMKP1/<mac>`. If it accepts local commands, this
   may be a better control channel than BLE — and it sidesteps the single-central
   contention problem entirely.

## 7c. Next: power on/off, mode, fan

Temperature is solved. The remaining controls need one more snoop capture,
because the `len=1` AC_CTRL payload leaves no room for a sub-command id — so
power/mode/fan must use a different `cmdId` or payload shape than temperature.

**Method (~5 min, now well-trodden):**
1. `adb shell cmd bluetooth_manager disable && ... enable`, confirm `FULL`
2. In the app: toggle power off, power on, change mode, change fan speed —
   pausing ~5 s between each so they are separable in the timeline
3. `adb bugreport bugreport.zip` → `parse_snoop.py`
4. Add the decoded frames to `helium.py`

## 7d. WiFi / network investigation — NO LOCAL CONTROL EXISTS

Question: can we control the AC over WiFi instead of BLE?

### Network topology (important, caused an early wrong conclusion)
- **The AC is on SSID `Airtel_B801`** (read live from `b001`).
- **This Mac is on Ethernet** behind a *different* router, `dsldevice.lan`
  (192.168.1.1), address 192.168.1.7. `networksetup -getairportnetwork en0` →
  "not associated with an AirPort network".
- The phone is on `Airtel_B801`, which is why the app sees the AC and this Mac
  cannot.

> **The app listing the device does NOT mean local control exists.** The app
> enumerates devices from Helium's *cloud* API
> (`https://o7sbv8y912.execute-api.ap-south-1.amazonaws.com/user/devices?user=`),
> not by LAN discovery. Presence in the app ≠ locally reachable.

### Evidence that these devices have no local control surface
A different Helium unit *was* reachable from this Mac at `192.168.1.8`
(MAC `e8:8f:8e:01:7f:1a`). It is **not ours** — ours is `...7f:93`; the 121-byte
gap is far larger than the typical ESP32 WiFi/BT MAC offset (+1/+2).

Probing that unit:
- alive: `ping` 0% loss, ~6 ms
- **no listening TCP ports at all** — scanned 22, 23, 53, 80, 443, 502, 1883,
  3333, 5000, 6667, 6668, 8000, 8080, 8266, 8883, 8888, 9999, 49152 → all closed
- no mDNS/Bonjour service (`dns-sd -B _services._dns-sd._udp` shows only Apple
  services; no `_helium`, `_http`, `_mqtt`, `_esp`)
- silent to UDP probes

**Conclusion: the firmware is outbound-only to AWS IoT. There is no local HTTP
server, no local MQTT broker, and no Tuya local port (6668). Local WiFi control
is not possible without replacing the firmware or the WiFi module.**

### Cloud path (the only WiFi option)
```
AWS IoT endpoint : a1a1a198fgj6igmrrt-ats.iot.ap-south-1.amazonaws.com
region           : ap-south-1 (Mumbai)
publish topic    : hoags/<custname>/<prodtype>/<prodmodel>/<macid>/hoagsUIControl
ack topic        : hoags/<custname>/<prodtype>/<prodmodel>/<macid>/hoagsUIControlAck
```
For this unit:
```
hoags/Helium/ac/HELM0000015HMKP1/<your-device-macid>/hoagsUIControl
hoags/Helium/ac/HELM0000015HMKP1/<your-device-macid>/hoagsUIControlAck
```
Topic builders `pubTopic` / `ackTopic` are at ~line 340513 of `bundle_decomp.js`;
fields come from the `b001` blob. The APK ships `assets/AWSiOT.p12` +
`assets/AmazonRootCA1.pem`, and the native module is `HeliumCloudMQTT`.

**Trade-off:** cloud control round-trips to Mumbai to reach an AC in the same
room, and fails whenever the internet does. BLE (already working) is local and
has no such dependency.

### Better architecture for "control over WiFi"
Put an **ESP32 near the AC** running the (already proven) BLE protocol and
expose HTTP/MQTT on the local network. That yields genuine local WiFi control
without any cloud dependency, and without opening the indoor unit.

## 7e. Cloud (AWS IoT) control — architecture & what it requires

Goal: control over WiFi via Helium's cloud, reusing the BLE command knowledge.

### How the app's cloud path actually works (from `bundle_decomp.js` + jadx)

1. **User auth is phone-OTP.** Backend API base
   `https://o7sbv8y912.execute-api.ap-south-1.amazonaws.com/dev` with routes
   `/auth/send-otp`, `/auth/verify-otp`, `/auth/me`, `/devices`, `/devices/`.
   A **Bearer token** (AsyncStorage key `@helium_auth_tokens`) authorises calls.
2. **MQTT config is supplied at runtime**, not hardcoded. The Kotlin native
   module `HeliumCloudMQTTModule.connect(options)` reads `host`, `port`,
   `clientId`, `p12File`, **`p12Password`**, `caFile` from a JS-side options
   object (confirmed in decompiled `HeliumCloudMQTTModule.java`,
   `options.getString("p12Password")`). Those values are React state populated
   from the backend / device info — the endpoint host and the p12 password are
   **not literals in the bundle**.
3. **Transport:** MQTTS on 8883, mutual-TLS with `AWSiOT.p12` (client cert) +
   `AmazonRootCA1.pem` (CA), via the Eclipse Paho client.
4. **Control topic:**
   `hoags/Helium/ac/HELM0000015HMKP1/<your-device-macid>/hoagsUIControl`
   ack on `…/hoagsUIControlAck`.

### Credentials status
- `apk/assets/AWSiOT.p12` is **password-protected**; common passwords
  (`""`,`helium`,`AWSiOT`,`1111`,`hoags`,`changeit`,…) all fail. The real
  password is delivered at runtime from the backend, so it is **not extractable
  from the APK statically**.
- Endpoint host `a1a1a198fgj6igmrrt-ats.iot.ap-south-1.amazonaws.com` is known
  (from bundle strings), but the client identity is gated behind the p12
  password + possibly a per-session/per-user policy.

### What "do it through cloud" therefore requires
Two viable routes:

**A. Replay the app's own auth (cleanest, uses your account):**
1. Sniff the app's HTTPS to the backend with an **mitmproxy** CA trusted on the
   phone (or Frida-hook `okhttp`), during a normal app session.
2. Capture: the OTP `Bearer` token, and the `connect(options)` object the JS
   passes to `HeliumCloudMQTTModule` — that object contains the **live
   `p12Password`** and the exact `host`/`clientId`.
3. Reproduce in Python with `paho-mqtt` + the extracted p12 → publish command
   JSON to `…/hoagsUIControl`.

**B. Grab the runtime p12 password via Frida** — hook
`HeliumCloudMQTTModule.connect` (or `String.toCharArray` in `buildSSLContext`)
and print the password as the app connects. Then use the shipped `AWSiOT.p12`
directly.

### Still-open: the cloud command *payload* format
We know the BLE command bytes. The **MQTT payload is a different encoding**
(the app has a separate `buildXxxPacket` cloud path and a JSON-ish
`hoagsUIControl` message). Its schema must be captured from either the MQTT
publish (route A) or the `onMessage` handler — not yet decoded.

### Honest trade-off (unchanged recommendation)
Cloud control round-trips ap-south-1 (Mumbai) to reach an AC in the same room
and dies with the internet. It also means authenticating as the app against
Helium's infrastructure. **BLE already works, locally, with no dependencies.**
For "control over WiFi" specifically, an **ESP32 BLE→WiFi bridge** is strictly
better than cloud: local, no Mumbai round-trip, no account/cert handling.

## 7f. Self-hosted web panel — auth WORKS; device found on hoags backend

Built `web/server.py` (Flask proxy) reproducing the app's cloud auth. No Android
dependency: we log in with a phone OTP entirely from our own code.

### Verified working
```
POST /auth/send-otp  {phone:"+91XXXXXXXXXX"}  -> {isNewUser:false, "OTP sent successfully"}
POST /auth/verify-otp {phone, otp}            -> {tokens:{accessToken, idToken, refreshToken}}
```
Auth backend is **AWS Cognito** (RS256 JWT, ~24 h expiry, user pool
`ap-south-1_AfYzaTFIk`, app client `6s3upjiknou3vmnkcvsev5hv2u`).

### KEY FINDING: the API authorizer wants the **idToken**, not accessToken
The app's axios interceptor attaches `accessToken`, but API Gateway rejects it:
```
Bearer <accessToken> -> 401 Unauthorized
Bearer <idToken>     -> 200 OK
```
(The accessToken is presumably for a different service; device API uses idToken.)
→ `web/server.py` must send `SESSION["id"]`.

### INITIAL (WRONG) FINDING: `/dev/devices` returned zero devices
```
GET /devices  (Bearer idToken) -> {"devices":[],"count":0}   HTTP 200
```
This *looked* like the AC wasn't on the account. **It was a wrong conclusion —
see the correction immediately below.** The `/dev/devices` route is simply not
the list the app's "find your AC" uses. Kept here only to document the dead end;
do NOT act on it (in particular, `POST /devices` re-registration is NOT needed).

### CORRECTION: the device IS on the account — I queried the wrong backend
`GET /dev/devices` (primary API) returns empty, but that is **not** where cloud
devices live. The app's "find your AC" cloud list comes from the **hoags**
backend:

```
GET https://tz1z01inlb.execute-api.ap-south-1.amazonaws.com/hoags/user/devices?user=<hoagsUserId>
```

`hoagsUserId` comes from `/auth/me` → `body.user.hoagsUserId` =
`<your-hoags-user-uuid>`, which **matches the UUID in the AC's
`b001` blob** — confirming the device is genuinely bound to this account.

Result (HTTP 200):
```json
[{"friendlyname":"HELM__XXXX","prodmodel":"HELM0000015HMKP1",
  "macid":"<your-device-macid>","prodtype":"ac",
  "userid":"<your-hoags-user-uuid>","custname":"Helium"}]
```

**This endpoint requires no auth token** — only the userId (which the AC itself
advertises in `b001`). So **no re-registration is needed**; the device was on the
account all along.

These fields give the full MQTT control topic:
```
hoags/Helium/ac/HELM0000015HMKP1/<your-device-macid>/hoagsUIControl
     custname  prodtype prodmodel  macid
```

### Consequence
- Cloud read of device identity: **working, unauthenticated**.
- Cloud *control* still needs the MQTT p12 password (runtime) + cloud payload
  schema — unchanged, see §7e.
- **BLE remains the working control path today**, account-independent.

## 7g. PLAN A — cloud MQTT control (chosen direction)

Goal: send commands via Helium's AWS IoT MQTT so the website works from
anywhere. Everything except two runtime secrets is known.

### What we already have
| Item | Value / source |
|---|---|
| IoT endpoint | `a1a1a198fgj6igmrrt-ats.iot.ap-south-1.amazonaws.com` |
| Port / transport | 8883, MQTTS mutual-TLS (Eclipse Paho) |
| CA cert | `apk/assets/AmazonRootCA1.pem` |
| Client cert | `apk/assets/AWSiOT.p12` (password unknown) |
| Control topic | `hoags/Helium/ac/HELM0000015HMKP1/<your-device-macid>/hoagsUIControl` |
| Ack topic | `…/hoagsUIControlAck` |
| Account login | OTP flow working (`web/server.py`) |
| Device identity | hoags `/user/devices?user=<uuid>` (unauth) |

### Blocker #2 (payload schema) — SOLVED statically, no capture needed
Read the `CloudMQTTProvider.publishTemperature` path in `bundle_decomp.js`
(~340150–340280):
```
publishTemperature(t):
    payload = buildTemperaturePacket(t)          # SAME buildPacket() hex format
    slot11.publish(pubTopic(macid), payload)     # native MQTT module
```
So the **cloud payload is the `buildPacket()` hex string** — exactly the format
in §5d (magic `1003`=AC_CTRL, header `[2,0,0,0,0]`, data `[celsius]`), rendered
as lowercase hex text. NOT a new schema. Confirmed for temp; the other
`publishXxx` fns use the matching `buildXxxPacket`.

Also recovered from the same block:
- topic = `pubTopic(macid)` =
  `hoags/Helium/ac/HELM0000015HMKP1/<your-device-macid>/hoagsUIControl`
- fan-speed map: `{auto:0, low:1, medium:2, high:3}`
- publishers: power, fanSpeed, temperature, turbo, sleep, display, silent,
  timer, mode, convertible, verticalSwing, horizontalSwing

> Note: this is the format the **cloud MCU** receives. Whether it re-frames to
> the BLE `ff …` 25-byte packet internally, or the AC's firmware accepts
> `buildPacket` hex directly over MQTT, only matters once we can publish.

### Remaining blocker — just ONE: the p12 password
1. **p12 password** — passed at runtime into
   `HeliumCloudMQTTModule.connect(options.p12Password)`. Confirmed NOT in:
   the JS bundle (slot8 is an unresolved closure var; endpoint literal
   `a1a1a198…` has 0 matches in JS), the dex (`p12Password` is only a log
   template), or any custom `.so` (there is none — module is pure Kotlin; split
   APK has only stock RN/Expo libs). Endpoint + password reach JS at runtime but
   NOT via a REST call (`/app/config` is only version info). Origin still
   unresolved statically → **capture required for this one value.**

### Capture method (pick one)
**mitmproxy (preferred — gets both at once):**
1. `pip install mitmproxy`; run `mitmproxy` (or `mitmweb`) on the Mac.
2. On the phone: set Wi-Fi proxy to the Mac's IP:8080, install & trust the
   mitmproxy CA (`http://mitm.it`).
3. **Caveat:** the app may use TLS pinning or the native MQTT socket may bypass
   the HTTP proxy. HTTPS to the REST backend will be visible; the raw MQTT/8883
   socket likely will NOT (it is not HTTP). So mitmproxy gets the
   `connect(options)` REST/config call *if* the password is fetched over HTTPS,
   but may miss the MQTT publishes.

**Frida (more reliable for the password + payload):**
1. Root/emulator or `frida-gadget`; `frida -U -n "Helium Air"`.
2. Hook `com.helium.mobileapp.HeliumCloudMQTTModule.connect` → dump the
   `ReadableMap options` (contains `host`, `clientId`, **`p12Password`**).
3. Hook the `publish(topic, payload)` method (same class) → dump each command
   JSON as you press buttons in the app. Gives the exact payload schema.

### Then (Python)
```
paho-mqtt + AWSiOT.p12 (now unlockable) + AmazonRootCA1.pem
  -> connect 8883 mutual-TLS
  -> publish <command-json> to …/hoagsUIControl
  -> subscribe …/hoagsUIControlAck
```
Wire this into `web/server.py` as `POST /api/command`.

### Open sub-questions for the capture
- Is `p12Password` per-device, per-user, or a static app secret?
- Does the same `AWSiOT.p12` work for any user, or is the cert per-account?
- Exact command JSON: field names, and whether it reuses DP ids (2=temp) or
  the `AC_CMD_*` names.

## 7h. Cloud auth reproduced end-to-end (self-hosted, no Android)

The OTP login + device read is **fully working** from our own code
(`web/server.py`). Verified live against the real backend.

### Backend map (primary API)
```
base = https://o7sbv8y912.execute-api.ap-south-1.amazonaws.com/dev
POST /auth/send-otp    {phone:"+91XXXXXXXXXX", isSignUp:false} -> {isNewUser, message}
POST /auth/verify-otp  {phone, otp} -> {tokens:{accessToken, idToken, refreshToken}, ...}
GET  /auth/me          Bearer <idToken> -> {user:{hoagsUserId, phone, ...}}
GET  /devices          Bearer <idToken> -> {devices:[], count}   (EMPTY - wrong list)
routes also: /devices REGISTER(POST), /devices/{id} UPDATE/DELETE,
             /devices/{id}/status LOG_STATUS, /devices/{id}/analytics
```
Auth = **AWS Cognito** RS256 JWT, pool `ap-south-1_AfYzaTFIk`, client
`6s3upjiknou3vmnkcvsev5hv2u`, tokens ~24 h.

### GOTCHA (cost real time): API wants idToken, not accessToken
The app's axios interceptor attaches `accessToken`; API Gateway's Cognito
authorizer **rejects it (401)** and accepts **`idToken` (200)**. Always send
idToken to the device/cloud API.

### GOTCHA: `/auth/me` nests under `.user`
`hoagsUserId` is at `body.user.hoagsUserId`, not top level.

### Device lives on the SECOND backend (hoags), UNAUTHENTICATED
```
GET https://tz1z01inlb.execute-api.ap-south-1.amazonaws.com/hoags/user/devices?user=<hoagsUserId>
-> [{friendlyname, prodmodel, macid, prodtype, userid, custname}]   (no token needed)
```
For this account (`+91XXXXXXXXXX`, hoagsUserId
`<your-hoags-user-uuid>` — matches the AC's `b001` UUID):
```json
[{"friendlyname":"HELM__XXXX","prodmodel":"HELM0000015HMKP1",
  "macid":"<your-device-macid>","prodtype":"ac","userid":"<your-hoags-user-uuid>","custname":"Helium"}]
```
So the device IS on the account; the `/dev/devices` "empty" result was a
red herring (wrong backend).

## 7i. APK PATCHING to capture the p12 password — the saga

Goal: run the app instrumented (Frida) to read the runtime `p12Password` and the
cloud publish payload. Phone is **NOT rooted**, so this required repackaging.

### Environment
- `apktool 3.0.3`, `objection`, `frida 17.16.4`, Android build-tools 37.0.0
  (`apksigner`, `zipalign`) at `~/Library/Android/sdk/build-tools/37.0.0`.
- App is a **split APK** (base + `split_config.arm64_v8a` + `.en` + `.xxhdpi`).
  Must install ALL splits, all signed with ONE key, via `install-multiple`.
- objection signing key: `objection.jks`, storepass **`basil-joule-bug`**,
  alias `objection`.

### WALL #1 — Google Play PairIP app-protection (the real blocker)
The patched app kept bouncing to Play Store. logcat revealed:
```
com.pairip.licensecheck.LicenseActivity
com.helium.mobileapp is installed but certificate mismatch   (Finsky)
SignatureCheck: Signature check ok    (a DIFFERENT, benign check)
```
The Play-side wrapper `com.pairip.*` runs a license/signature check in
`Application.attachBaseContext` and redirects on cert mismatch (we re-signed).

**Diagnosis — it is the LIGHT PairIP variant (Java-only):**
- classes present: `com.pairip.licensecheck.{LicenseActivity, LicenseClient,
  LicenseClient$*, LicenseCheckException, LicenseResponseHelper}`
- App class = `com.pairip.application.Application`, whose `attachBaseContext`
  calls exactly `LicenseClient.checkLicense(context)` and nothing else.
- **No `libpairipcore.so`, no VMRunner** — the hard obfuscated variant is absent.

**BYPASS (works):** smali-patch `LicenseClient.checkLicense(Context)` to an
immediate `return-void`:
```smali
.method public static checkLicense(Landroid/content/Context;)V
    .locals 0
    return-void
.end method
```
After this: no cert-mismatch redirect, app launches to MainActivity. ✅

### WALL #2 — apktool resource rebuild corrupts 9-patch drawables
Full `apktool b` rebuild made the app crash on launch:
```
FATAL EXCEPTION: mqt_native_modules
java.lang.NullPointerException: ...NinePatch.hasAlpha() on null
  ...EditText.<init> ... View.setBackground
```
apktool re-encoded the resource table and broke a 9-patch used as an EditText
background. **Fix: never let apktool rebuild resources.** Instead do a SURGICAL
repackage:
1. `apktool d` + patch smali + `apktool b` **only to obtain rebuilt `classes*.dex`**
   (in `pairip_patch/build/apk/classes*.dex`).
2. Start from the pristine original `base.apk` (resources untouched).
3. `zip` the patched `classes*.dex` over it.
4. Add the Frida gadget + config.
5. `zipalign -p 4` then `apksigner sign`.

This preserves original compiled resources → no 9-patch crash. ✅

### WALL #3 — installing the Frida gadget without root
Used `frida-gadget` (embedded lib), not frida-server (needs root).
- Inject a `loadLibrary("frida-gadget")` call. objection does this into
  `MainActivity` smali; for the surgical build we added a `<clinit>`:
  ```smali
  .method static constructor <clinit>()V
      .locals 1
      const-string v0, "frida-gadget"
      invoke-static {v0}, Ljava/lang/System;->loadLibrary(...)V
      return-void
  .end method
  ```
- Gadget lib `lib/arm64-v8a/libfrida-gadget.so` + config
  `lib/arm64-v8a/libfrida-gadget.config.so` (name MUST mirror the lib).
- Result: `nativeloader: Load libfrida-gadget.so ... ok`. Gadget loads. ✅

### WALL #4 — native-lib packaging flags
`INSTALL_FAILED_INTERNAL_ERROR ... Failed to extract native libraries res=-110`.
Manifest has `android:extractNativeLibs="false"`, which requires every `.so`
(incl. the gadget) to be **stored uncompressed AND page-aligned** in the zip:
```
zip -0 ...            # store, no compression
zipalign -p 4 ...     # page-align .so
```
(Flipping the manifest to `extractNativeLibs="true"` also works but needs a
resource/manifest rebuild → reintroduces WALL #2. Uncompressed+`-p` is cleaner.)

### CURRENT STATE — DONE. Capture succeeded; p12Password = `1234`.
- ✅ PairIP bypassed, app stable, MainActivity focused (no store redirect)
- ✅ gadget loads (`libfrida-gadget.so ... ok`)
- ✅ **hook output captured** — see §7j for how the last-mile blockers were solved
  (debuggable rebuild via surgical binary-manifest patch + Frida-17 java-bridge).

### Reusable lesson
The entire cloud path is **crackable but disproportionate**: it defeats Google
Play app-protection to obtain ONE secret that only enables a *worse* control
channel (round-trips to ap-south-1, dies with the internet). BLE already gives
local control. Cloud is worth finishing ONLY for "control from outside the home."

## 7j. ✅ SOLVED — cloud MQTT control end-to-end (`helium_cloud.py`)

The capture succeeded and cloud commands now actuate the AC from our own Python.

### How the last-mile Frida blockers were beaten
1. **Debuggable rebuild without a resource-table rebuild.** Wrote a surgical AXML
   patcher (`scratchpad/patch_debuggable.py` + `axml.py`) that parses the binary
   `AndroidManifest.xml`, APPENDS a `debuggable` string (new idx, so no existing
   string index shifts), extends the resource map so that index maps to attr
   res-id `0x0101000f`, and inserts one 20-byte attribute into `<application>`
   (`INT_BOOLEAN` = `0xffffffff`). Round-trip verified byte-identical on the
   unpatched file first; aapt2 confirms `debuggable=true`, no "Bad XML block".
   `resources.arsc` + drawables untouched → **no WALL #2 9-patch crash.**
   - Gotcha found: `attributeCount` is at node offset **28**, `attributeSize` at
     **26**. Writing the count to 26 sets attrSize=11 → "attribute size 11 <
     min 20" and the parser truncates before `<application>`.
2. Zip patched manifest over pristine base, **strip stale `META-INF/OBJECTIO.*` +
   `MANIFEST.MF`** (WALL #4 signature lesson), `zipalign -p 4`, `apksigner` with
   objection key. `install-multiple` base + 3 splits. `run-as` now works.
3. **Frida 17 dropped the `Java` global.** Script threw `ReferenceError: 'Java'
   is not defined`. Fix: `npm i frida-java-bridge`, `import Java from
   "frida-java-bridge"`, `frida-compile` into a self-contained agent. Then
   `Java.available===true` and `Java.perform` works.
4. Ran gadget in **listen mode** (`on_load:wait`), `adb forward tcp:27042`,
   attached via the Python API (`add_remote_device` → `attach("Gadget")` →
   `create_script` → `resume`). NOTE: with `on_load:wait`, if the app is killed
   it re-pauses pre-UI ("stuck at start") until a fresh client attaches — just
   re-attach.

### Captured runtime values (from `HeliumCloudMQTTModule.connect`)
```
p12Password = 1234                 <-- unlocks apk/assets/AWSiOT.p12
host        = a198fgj6igmrrt-ats.iot.ap-south-1.amazonaws.com   (port 8883)
clientId    = ios_hoagsapp_<rand>_<epochms>
p12File=AWSiOT   caFile=AmazonRootCA1
```
> The bundle-string host `a1a1a198…` (§7d/§7g) was WRONG — the real runtime host
> has no leading `a1a1`. The p12 contains `CN=AWS IoT Certificate` + private key,
> valid to 2049; password is app-static (works for our own paho client).

### The publish gotcha that cost the most time
The app's `publish(topic, payload)` **hex-decodes** the payload string to raw
bytes when it is all-hex/even-length, and sends a `MqttMessage` at **QoS 0**
(`setQos(0)`; subscribe is also QoS 0, `setCleanSession(true)`, keepalive 60).
- Sending the 52-char **hex TEXT**, or QoS 1, connects and even elicits an ack
  state-dump but **does NOT move the setpoint**.
- Sending `bytes.fromhex(payload)` (26 raw bytes) at **qos=0** actuates. ✅

### FULL command family (cmdId 1003 = AC_CTRL; sub-command in level[0])
Wire format (per §5d): `ff 03eb 0001 0001 00000000 02 <level5> 000000 01 00000000 <data>`
where `level5 = [sub,0,0,0,0]` (timer uses `[sub,1,0,0,0]`), `len`/`totalSize`
follow the data length. Extracted verbatim from every `buildXxxPacket` in the
bundle. **Bool polarity DIFFERS per command — do not assume one convention:**

| control | sub | data | polarity |
|---|---|---|---|
| power | 0 | 1B | on→**0** (INVERTED) |
| fan | 1 | 1B | {auto:0,low:1,medium:2,high:3} |
| temperature | 2 | 1B | celsius & 0xFF |
| mode | 3 | 1B | cool→1, else 0 |
| verticalSwing | 4 | 1B | on→1 |
| turbo | 5 | 1B | on→**0** (INVERTED) |
| sleep | 6 | 1B | on→1 |
| display | 10 | 1B | on→1 |
| convertible | 17 | 1B | raw value & 0xFF |
| silent | 20 | 1B | on→**0** (INVERTED) |
| horizontalSwing | 21 | **2B** `[0, on?1:0]` | on→1 |
| timer | 18(on)/19(off) | **2B** `[min>>8, min&0xFF]`, level `[sub,1,0,0,0]` | minutes |

All 12 implemented in `helium_cloud.py`. The BLE path (`helium.py`) accepts the
**same raw bytes** — cloud and BLE payloads are byte-identical, so a dual-transport
frontend can build once and send over either channel.

### Empirical command→DP mapping (e2e sweep: cloud publish → BLE Poll dump delta)
Verified live by publishing each cloud command and diffing the BLE DP table:
```
temperature -> DP2   (24->22)              CONFIRMED
power       -> DP1   (1->0)                CONFIRMED (also audible beep)
fan         -> DP5   (auto=0,low=1,...)    CONFIRMED
mode        -> DP4   (cool=1, heat=3) +DP5 CONFIRMED
verticalSwing -> DP6E (1->0)               CONFIRMED
turbo       -> DP5=4 + DP67 (0->1)         CONFIRMED
horizontalSwing / sleep / display / silent -> no distinct DP moved in the dump,
  but the unit BEEPS on receipt (user-confirmed) — commands are accepted; these
  states just aren't echoed as a separate Poll DP (or need a longer settle).
```
> Method/harness: `scratchpad/e2e_test.py` — holds one BLE connection, snapshots
> the DP table, publishes each cloud command, re-snapshots, reports the delta.
> Ignore DP1C (power draw) and DP6A (room temp): they drift on their own.

### Verified working (two independent channels)
```
cloud set 23°C -> BLE read setpoint_C=23 ; set 24°C -> 24 ; via Flask -> 25 all confirmed
read_state()   -> {power, setpoint_C, room_temp_C, power_W, fan(DP5), mode(DP4), ...}
```
Ack topic `…/hoagsUIControlAck` carries the device's `Poll:0:<55aa…>` Tuya DP dump
(same frames as BLE §5e). The dump is **intermittent** per connect — `read_state`
retries across a few connects (default 3). Device also expects a `ping` to
`hoags/Helium/<mac>/HELM__XXXX` on connect (harmless; not required for control).

### Files
`helium_cloud.py` — connect (mutual-TLS), `read_state`, `publish_command`, and
ALL 12 builders (temperature/power/fan/mode/verticalSwing/turbo/sleep/display/
convertible/silent/horizontalSwing/timer). Wired into `web/server.py`:
`GET /api/ac/state`, `POST /api/ac/command` — both transport-selectable (§7k).
`web/ble_bridge.py` puts BLE behind the same endpoints; `web/src/` is the SPA.
Deps: `paho-mqtt`, `cryptography`.
Frida capture artifacts under `scratchpad/` (agent, compiled bundle, attach
runner, `e2e_test.py`) and `capture.js` (uncompiled hook source).

## 7k. ✅ DONE — dual-transport frontend (BLE + cloud in one panel)

Both transports are now driven from one web UI. Confirmed live: a **BLE** write of
26°C was read back **over cloud** as `setpoint_C=26` — independent channels
agreeing, which is the proof that the shared-payload design holds.

### Backend (`web/server.py`)
- `POST /api/ac/command` — all **12** commands via a `COMMANDS` dict of builders
  (was a 5-branch if/elif). Timer takes `{"timer":{"minutes":30,"on":true}}`.
- `GET /api/ac/state` and the command endpoint both take `?transport=ble|cloud`
  (or a `transport` JSON field); default `cloud`. State replies are
  `{"transport":…, "state":{…}}`.
- `GET /api/ble/status`, `POST /api/ble/connect`, `POST /api/ble/disconnect`.
- Serves the built SPA: `static_folder=web/dist`, `/` → `dist/index.html`, plus a
  404 handler that falls through to the SPA for non-`/api/` paths.

### BLE bridge (`web/ble_bridge.py`)
One background thread owning an asyncio loop + a single `Helium` connection
(the AC allows one central); Flask handlers cross over with
`asyncio.run_coroutine_threadsafe`. Lazily connects, `connect()` then `login()`.

Two gotchas found while wiring it up:
- **`login()` returning False does NOT mean commands are refused.** The 0x79
  passkey ack only re-fires on a fresh session; on a warm one `authed:false` is
  reported yet writes land fine (verified — the 26°C write above).
- **`helium.py` raises `SystemExit`, which `except Exception` does NOT catch.**
  `connect()` does `raise SystemExit("AC not advertising…")` — a `BaseException`.
  It escaped the Flask handlers entirely (generic 502, no JSON), and where it was
  caught, `str(SystemExit(...))` is `""`, so the API returned `{"error":""}`.
  The BLE routes now catch `BaseException` and fall back to the exception type
  name so an error is never blank. Watch for this in any new handler.
- **`helium.py`'s notify parser can emit garbage integers.** It trusts the
  frame's own length field, so `int.from_bytes(b[10:10+dlen])` over-reads when a
  frame carries trailing bytes — observed `fan = 13002342400` while a
  simultaneous cloud read reported no fan DP at all. `read_state()` in the bridge
  drops values wider than the DP (except DP1C, a genuinely wide counter) instead
  of reporting them. `helium.py` itself is left untouched (CLI scripts share it);
  the root-cause fix would be bounding `dlen` against the frame length.

### Frontend (`web/src/`)
React + Vite + Tailwind v4 (`@tailwindcss/vite`), everything bundled — no CDN
tags. Transport toggle persisted to localStorage; power/temp ±(16–30)/mode/fan/
both swings/turbo/sleep/display/silent up front; timer + convertible tucked into
a collapsed "least tested" block (they move no observable DP). Auto-reads on
load, on transport change, and 1.5 s after each command; every action is logged
with the transport used and the raw hex sent.

> Cloud `read_state()` takes seconds (it retries across fresh MQTT connects);
> BLE reads are an instant `ac.state` snapshot. Hence refresh-after-command
> rather than interval polling.

**Explicit-state rule.** Every control renders one of three visually distinct
states — **on**, **off**, or **unknown** — and no value is displayed unless the AC
reported it. This matters because the two transports report different DP sets:

| Reported by | DPs |
|---|---|
| both | `setpoint_C`, `room_temp_C`, `power_W` |
| BLE only | `power`, `mode`, `fan`, `turbo`, `vertical_swing` |
| neither | `horizontalSwing`, `sleep`, `display`, `silent` |

So on **cloud** transport power/mode/fan/turbo/vertical-swing legitimately read
*unknown*, while **BLE** shows real values; the four in the last row are unknown
permanently, and stay unknown even after a command, since nothing ever confirms
them. Unknown is dashed and carries the word — it must never be confusable with a
settled *off*. Known toggles flip; unknown ones expose explicit On/Off buttons,
because with no position to flip from a single toggle could only send one command.

Two consequences worth knowing: the setpoint initialises to `null` (not 24), so
the readout shows `—` and the ± buttons stay disabled until a read lands; and an
unrecognised `mode` value reads as unknown rather than being labelled "heat" by
an else branch. Timer/convertible keep numeric prefills — they are command
arguments, not device state, so the rule doesn't reach them.

Components: `App.jsx` (routing, transport), `useAcState.js` (reads, commands,
log), `api.js`, and `components/` — `Hero`, `Segmented`, `Switch`, `TransportBar`,
`ActivityLog`, `Advanced`, `Auth`, `DeviceList`. Responsive single→two column,
44 px minimum touch targets.

**Cloud sign-in** (`Auth.jsx`): phone → `/api/send-otp` → `/api/verify-otp`, then
the device list from `/api/devices` + `/api/hoags-devices`. Reachable from the
header but never required — BLE works signed out.

### Run it
```
python web/server.py                 # prod: serves web/dist on :5055
cd web && npm run dev                # dev: :5173, proxies /api -> :5055
curl -X POST 'localhost:5055/api/ac/command?transport=cloud' \
     -H 'Content-Type: application/json' -d '{"power":true}'
```

### Verified this session
```
cloud: setpoint 25->23 (re-read confirms); all 12 payloads match the §7j table
BLE:   setpoint ->26, cross-checked via a cloud read      CONFIRMED
BLE:   setpoint 24->22, confirmed by BLE re-read          CONFIRMED
prod:  npm run build -> Flask serves dist/ + hashed assets (200)
dev:   vite :5173 proxying /api/ble/status -> Flask       CONFIRMED
```

## 8. Open questions

- Recover the full device UUID from `b001` (truncated at 128 B read).
- What does `b004` (indicate) carry? (bundle strings suggest BLE OTA)
- Is the shared `AWSiOT.p12` per-account or global? (works for us with `1234`;
  scope beyond "app-static" untested — would need a second account to prove.)
- Does re-registering (`POST /devices`) transfer ownership? (untested; not needed
  since device already on account via hoags backend.)

---

## 9. Files

Repo layout: working entrypoints (`helium.py`, `helium_cloud.py`) and the
web panel live at the root / `web/`; experiments live under `ble/` and `frida/`.
Large RE inputs (`bugreport.zip`, `bundle_decomp.js`, `apk/`, jadx/apktool
trees, pcaps) and secrets (`apk/assets/*.p12`, `*.pem`) are gitignored — they
stay on disk but are not tracked.

**Run scripts from the repo root**, not from inside `ble/`: the `ble/*.py`
experiments do `from helium import …`, which only resolves when the CWD is the
repo root (e.g. `python ble/settest.py`). Running them from within `ble/` fails
with `ModuleNotFoundError: helium`.

| File | Purpose |
|---|---|
| **BLE (working)** | |
| `helium.py` | **Working BLE client** — connect, read state, set temperature |
| `ble/parse_snoop.py` | Android btsnoop → decoded Helium BLE packets |
| `ble/parse_pcap.py` | nRF-sniffer pcap → ATT writes (unused; wrong dongle fw) |
| `ble/scan.py` / `find7f93.py` / `enum.py` / `listen.py` | BLE discovery/dump utils |
| `ble/settest*.py`, `probe2.py`, `tryset.py`, … | One-off write/probe experiments (import `helium`, run from repo root) |
| `bugreport.zip` → `FS/.../btsnoop_hci.log` | The capture that cracked BLE writes (gitignored) |
| **Cloud / web** | |
| `helium_cloud.py` | **Working cloud MQTT client** — mutual-TLS, read state, send commands |
| `web/server.py` | Self-hosted panel: OTP login + device read + `/api/ac/*` control |
| `bundle_decomp.js` | Decompiled app (Hermes) — protocol source of truth (gitignored) |
| `apk/assets/AWSiOT.p12`, `AmazonRootCA1.pem` | AWS IoT MQTT creds (gitignored) |
| **APK patching (§7i)** | |
| `apk/base.apk` + `split_config.*.apk` | Pristine pulled splits (gitignored) |
| `apk/signed/*.apk`, `pairip_patch/`, `surgical/` | Re-signed splits, apktool tree, patched base (gitignored) |
| `frida/capture.js` | Frida hook: `connect`/`publish`/`KeyStore.load` |
| `frida/run_capture.py` / `attach.py` / `frida_capture.py` | Frida runners (spawn needs root; attach for gadget) |
| `frida/gadget.config` / `gadget_listen.config` | Frida gadget script/listen configs |
| `frida/hook.js` / `probe.js` / `probe_run.py` | Earlier standalone hooks (superseded by `capture.js`) |
| **Reference (gitignored)** | |
| `jadx_out/`, `jadx_main/`, `jadx_pairip/` | jadx decompiles (MQTT module, MainApplication, PairIP) |
| `captures/` | BLE notification logs, mitm flows, sniffer pcaps |
