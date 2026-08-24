#!/usr/bin/env python3
"""
SinricPro → Helium AC bridge.

Lets Google Assistant control the AC ("Hey Google, turn on AC") without Nabu Casa,
Home Assistant, or exposing any inbound port. SinricPro publishes a free Google
Home (and Alexa) integration; this process holds an *outbound* websocket to their
cloud, receives the voice-triggered commands, and translates them into the same
cloud MQTT payloads the rest of this project sends.

    "Hey Google…" → Google Home → SinricPro cloud → (this bridge) → AWS IoT → AC

State flows back the same way. The AC publishes a full DP dump to its ack topic
whenever something changes — including changes made on the IR remote, which never
reach this bridge otherwise — so the bridge holds that subscription open and
raises the matching SinricPro events, keeping Google in sync with the unit:

    AC → AWS IoT → (this bridge) → SinricPro cloud → Google Home

Only the `cloud` transport is used — this box has no Bluetooth radio near the unit.

Setup and running: see bridge/README.md. Credentials come from `.env` (see
`.env.example`): SINRICPRO_APP_KEY, SINRICPRO_APP_SECRET, SINRICPRO_AC_DEVICE_ID.
"""
import os
import sys
import time
import queue
import asyncio
import logging
import threading

# import the project modules from the repo root (one dir up); `config` loads .env
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config  # noqa: E402  (side effect: populates os.environ from .env)
import helium_cloud as h  # noqa: E402

from sinric import SinricPro, SinricProConstants  # noqa: E402
import sinric._sinricpro_websocket as _spws  # noqa: E402

log = logging.getLogger("helium-sinric")

# The SDK calls websockets.connect(ping_interval=30000, ping_timeout=10000), but
# the `websockets` lib takes those in SECONDS — so keepalive pings are ~8h apart,
# i.e. effectively off, and a dropped SinricPro socket goes undetected forever
# (device shows "not responding"). Force real second-based keepalive so a dead
# peer is noticed within ~ping_interval+ping_timeout and the socket is closed.
_orig_ws_connect = _spws.client.connect


def _ws_connect_with_keepalive(*args, **kwargs):
    kwargs["ping_interval"] = 30
    kwargs["ping_timeout"] = 15
    return _orig_ws_connect(*args, **kwargs)


_spws.client.connect = _ws_connect_with_keepalive

APP_KEY = os.environ.get("SINRICPRO_APP_KEY", "")
APP_SECRET = os.environ.get("SINRICPRO_APP_SECRET", "")
DEVICE_ID = os.environ.get("SINRICPRO_AC_DEVICE_ID", "")

TEMP_MIN, TEMP_MAX = 16, 30          # unit's accepted setpoint range (README)
DEFAULT_MODE = "cool"                # what AUTO / a bare power-on maps to

# DPs the device reports in its `Poll:` dumps (PROTOCOL §5e).
DP_POWER = 0x01                      # 1 = running. NOTE the *report* polarity is
                                     # plain, unlike power_payload()'s inverted
                                     # command byte — do not reuse that mapping.
DP_SETPOINT = 0x02                   # target temperature °C
DP_MODE = 0x04                       # operating mode, enum (see _google_mode)
DP_ROOM_TEMP = 0x6A                  # room/indoor temperature °C

# This unit's remote offers Cool, Monsoon (dry) and "AI Cool" — no heat. Google's
# thermostat vocabulary is only AUTO/COOL/HEAT, so the two smart/dry modes both
# land on AUTO; it is the honest nearest fit and keeps the tile from lying about
# heating. DP 0x04 == 1 is cool (mode_payload encodes cool as 1); the other enum
# values are unmapped, hence the log line in _google_mode.
MODE_COOL = 1

REPORT_SEC = 60                      # push current temp to Google this often
STALE_SEC = 900                      # stop reporting a reading older than this
IDLE_POLL_SEC = 5                    # how long the worker waits for a command
WATCHDOG_SEC = 20                    # how often to check the SinricPro socket
WATCHDOG_GRACE = 45                  # let the first connection settle before watching

# last values we told the AC, so we can echo sensible state back to Google
_state = {"power": "Off", "setpoint": 24, "mode": DEFAULT_MODE}

# Latest state heard *from* the AC. The device pushes a full DP dump whenever
# something changes — including changes made on the IR remote, which never touch
# this bridge — so this is how we learn about them. `None` until the device has
# actually told us (so we never report a fabricated value).
_cache = {"room_temp": None, "room_temp_at": 0.0}
_cache_lock = threading.Lock()

# last values we pushed to SinricPro, so we only raise an event on a real change
# (SinricPro rate-limits events, and Google gets noisy if you spam it)
_reported = {"power": None, "setpoint": None, "mode": None, "mode_dp": None}

# set once the SinricPro client exists, so the async reporter can raise events
_client = None


def _plausible_temp(t):
    return t is not None and 0 < t < 60


def _cache_room_temp(t):
    if _plausible_temp(t):
        with _cache_lock:
            _cache["room_temp"] = t
            _cache["room_temp_at"] = time.time()


def _raise(event, data, what):
    """Push one state event to SinricPro, tolerating a not-yet-open socket.

    Safe to call from the MQTT thread: raise_event only appends to a plain
    thread-safe queue.Queue, which the SDK's asyncio task drains once connected.
    """
    if _client is None:
        return
    try:
        _client.event_handler.raise_event(DEVICE_ID, event, data=data)
        log.info("reported %s to Google", what)
    except Exception as e:  # noqa: BLE001 — a failed report must not kill the listener
        log.warning("report of %s failed: %s", what, e)


def _google_mode(power, mode_dp):
    """Map the device's power + mode DPs onto a Google thermostat mode."""
    if not power:
        return SinricProConstants.THERMOSTAT_MODE_OFF
    if mode_dp is None or mode_dp == MODE_COOL:
        return SinricProConstants.THERMOSTAT_MODE_COOL
    log.info("DP 0x%02X = %s is an unmapped mode — reporting AUTO", DP_MODE, mode_dp)
    return SinricProConstants.THERMOSTAT_MODE_AUTO


def _report_device_state(dps):
    """Mirror a device-reported DP dump up to Google, on change only.

    Without this the bridge is one-way: Google only ever sees state it asked for
    itself, so anything done on the remote (or the vendor app) leaves Google
    showing a stale power/setpoint indefinitely.
    """
    power = dps.get(DP_POWER)
    if power is not None:
        state = (SinricProConstants.POWER_STATE_ON if power
                 else SinricProConstants.POWER_STATE_OFF)
        if state != _reported["power"]:
            _reported["power"] = state
            _state["power"] = state
            _raise(SinricProConstants.SET_POWER_STATE, {"state": state},
                   f"power {state}")

    setpoint = dps.get(DP_SETPOINT)
    if setpoint is not None and TEMP_MIN <= setpoint <= TEMP_MAX:
        if setpoint != _reported["setpoint"]:
            _reported["setpoint"] = setpoint
            _state["setpoint"] = setpoint
            _raise(SinricProConstants.TARGET_TEMPERATURE,
                   {"temperature": float(setpoint)}, f"setpoint {setpoint} C")

    # Mode is derived from power *and* the mode DP, so a dump carrying only one
    # of them still yields the right answer — fall back to what we last knew.
    if power is not None or DP_MODE in dps:
        gmode = _google_mode(
            power if power is not None else (_reported["power"] ==
                                             SinricProConstants.POWER_STATE_ON),
            dps.get(DP_MODE, _reported["mode_dp"]),
        )
        if DP_MODE in dps:
            _reported["mode_dp"] = dps[DP_MODE]
        if gmode != _reported["mode"]:
            _reported["mode"] = gmode
            _raise(SinricProConstants.SET_THERMOSTAT_MODE,
                   {SinricProConstants.MODE: gmode}, f"mode {gmode}")


# ---------------------------------------------------------------------------
# Helium I/O runs on ONE dedicated thread that owns the MQTT client, so the
# asyncio event loop is never blocked by a (re)connect and MQTT access is
# serialized. Commands are QoS-0 fire-and-forget — the device sends no reliable
# ack — so callbacks enqueue and report success optimistically.
# ---------------------------------------------------------------------------
_q: "queue.Queue[str]" = queue.Queue()


def _on_ack(_topic, text):
    """Absorb a DP dump from the device: cache the room temp, mirror state up.

    The device pushes one of these whenever a DP changes, so this is the only
    place a remote-control change can enter the bridge.
    """
    dps = h.parse_ack(text)
    if not dps:
        return
    _cache_room_temp(dps.get(DP_ROOM_TEMP))
    _report_device_state(dps)


def _worker():
    """Own the MQTT client: connect eagerly, keep it up, publish queued commands.

    The connection is established at startup rather than on the first command,
    because its ack subscription is what feeds `_on_ack`. Deferring it would mean
    hearing nothing from the AC until Google happened to send something.
    """
    cli = None
    while True:
        if cli is None:
            try:
                log.info("connecting to AWS IoT…")
                cli = h.connect(on_ack=_on_ack, timeout=20)
                log.info("listening for AC state on %s", h.ACK_TOPIC)
            except Exception as e:  # noqa: BLE001 — keep retrying, never exit
                log.warning("AWS IoT connect failed, retrying: %s", e)
                time.sleep(10)
                continue

        try:
            payload = _q.get(timeout=IDLE_POLL_SEC)
        except queue.Empty:
            # idle: paho reconnects on its own (and _on_connect re-subscribes),
            # so just note a drop rather than tearing the client down under it
            if not cli.is_connected():
                log.warning("AWS IoT link down — paho is reconnecting")
            continue

        for attempt in (1, 2):
            try:
                h.publish_command(payload, cli=cli)
                break
            except Exception as e:  # noqa: BLE001 — reconnect on any failure
                log.warning("publish failed (attempt %d/2): %s", attempt, e)
                try:
                    cli.loop_stop()
                    cli.disconnect()
                except Exception:
                    pass
                cli = None
                try:
                    cli = h.connect(on_ack=_on_ack, timeout=20)
                except Exception as e2:  # noqa: BLE001
                    log.warning("reconnect failed: %s", e2)
                    cli = None
                    break
        else:
            log.error("gave up on payload %s", payload)


def send(payload: str):
    """Queue one already-built hex payload for delivery to the AC."""
    _q.put(payload)


def _clamp_temp(t) -> int:
    return max(TEMP_MIN, min(TEMP_MAX, int(round(float(t)))))


async def _report_current_temperature():
    """SinricPro event_callbacks entrypoint: push cached room temp to Google on
    an interval. The AC has no humidity sensor, so humidity is reported as 0.

    The device only reports when a DP changes, and it goes quiet entirely while
    idle or powered off — so a cached reading can outlive its truth. Past
    STALE_SEC we stop reporting rather than keep asserting a stale number.
    """
    while True:
        await asyncio.sleep(REPORT_SEC)
        with _cache_lock:
            rt, at = _cache["room_temp"], _cache["room_temp_at"]
        if rt is None or _client is None:
            continue
        age = time.time() - at
        if age > STALE_SEC:
            log.warning("room temp is %d min old — not reporting", age // 60)
            continue
        _raise(SinricProConstants.CURRENT_TEMPERATURE,
               {"temperature": float(rt), "humidity": 0.0},
               f"current temp {rt} C")


def _sinric_socket_alive():
    conn = getattr(getattr(_client, "socket", None), "connection", None)
    return conn is not None and getattr(conn, "open", False)


def _watchdog():
    """The SDK never reconnects: if its websocket drops, the process keeps
    running while SinricPro shows the device offline ("not responding"). Watch
    the socket and, once it's down, exit non-zero so systemd restarts us with a
    fresh connection (Restart=on-failure). Combined with real keepalive pings, a
    drop is detected within ~a minute instead of never."""
    time.sleep(WATCHDOG_GRACE)
    while True:
        if not _sinric_socket_alive():
            log.error("SinricPro websocket is down — exiting for a clean restart")
            os._exit(1)
        time.sleep(WATCHDOG_SEC)


# ---------------------------------------------------------------------------
# SinricPro request callbacks. Each is a *plain* function returning (True, value)
# — the SDK calls it synchronously and expects that tuple (see _power_controller
# / _temperature_controller / _thermostat_controller in the sinricpro package).
# ---------------------------------------------------------------------------
def on_power_state(device_id, state):
    """state is "On" / "Off"."""
    on = (state == SinricProConstants.POWER_STATE_ON)
    log.info("power -> %s", state)
    send(h.power_payload(on))
    _state["power"] = state
    # Google already knows — record it so the device's confirming dump doesn't
    # bounce straight back as an event. A dump that *disagrees* still will.
    _reported["power"] = state
    _reported["mode"] = _google_mode(on, _reported["mode_dp"])
    return True, state


def on_target_temperature(device_id, temperature):
    """Absolute setpoint, e.g. "set AC to 24"."""
    t = _clamp_temp(temperature)
    log.info("setpoint -> %d C", t)
    send(h.temperature_payload(t))
    _state["setpoint"] = t
    _reported["setpoint"] = t     # suppress the echo; see on_power_state
    return True, t


def on_set_thermostat_mode(device_id, mode):
    """mode is COOL / HEAT / AUTO / OFF (Google's thermostat modes).

    This unit cools only — its remote offers Cool, Monsoon and "AI Cool". HEAT is
    refused rather than silently doing something else, so Google reports a failure
    instead of the tile claiming a mode the hardware cannot enter.
    """
    mode = (mode or "").upper()
    log.info("mode -> %s", mode)
    if mode == SinricProConstants.THERMOSTAT_MODE_OFF:
        send(h.power_payload(False))
        _state["power"] = _reported["power"] = "Off"
        _reported["mode"] = mode
        return True, mode
    if mode == SinricProConstants.THERMOSTAT_MODE_HEAT:
        log.warning("HEAT requested but this AC cannot heat — refusing")
        return False, mode
    # COOL / AUTO → make sure it's on, then cool. AUTO has no separate command:
    # mode_payload is binary (cool / not-cool), so the unit's own smart modes
    # can't be selected remotely — only observed.
    send(h.power_payload(True))
    send(h.mode_payload("cool"))
    _state["power"] = _reported["power"] = "On"
    _state["mode"] = "cool"
    _reported["mode"] = SinricProConstants.THERMOSTAT_MODE_COOL
    return True, mode


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    missing = [n for n, v in (
        ("SINRICPRO_APP_KEY", APP_KEY),
        ("SINRICPRO_APP_SECRET", APP_SECRET),
        ("SINRICPRO_AC_DEVICE_ID", DEVICE_ID),
    ) if not v]
    if missing:
        raise SystemExit(
            "Missing SinricPro settings: " + ", ".join(missing) + "\n"
            "Add them to .env (see .env.example) — create the device at "
            "https://sinric.pro. Details in bridge/README.md."
        )

    global _client

    # helium_cloud prints every MQTT [ack]/[pub] to stdout; the device polls
    # constantly so that floods the journal. Send stdout to /dev/null — our logs
    # (and the SDK's) go to stderr, so they're unaffected.
    sys.stdout = open(os.devnull, "w")

    # start the MQTT worker (which also opens the state listener) before
    # accepting commands
    threading.Thread(target=_worker, name="helium-mqtt", daemon=True).start()
    threading.Thread(target=_watchdog, name="helium-watchdog", daemon=True).start()

    callbacks = {
        SinricProConstants.SET_POWER_STATE: on_power_state,
        SinricProConstants.TARGET_TEMPERATURE: on_target_temperature,
        SinricProConstants.SET_THERMOSTAT_MODE: on_set_thermostat_mode,
    }

    _client = SinricPro(
        APP_KEY, [DEVICE_ID], callbacks,
        event_callbacks=_report_current_temperature,
        enable_log=False, restore_states=False, secret_key=APP_SECRET,
    )
    client = _client
    log.info("bridge up — device %s; waiting for Google/SinricPro commands", DEVICE_ID)

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(client.connect())
    except KeyboardInterrupt:
        log.info("shutting down")
        return
    # connect() only returns/raises when the connection has failed; exit non-zero
    # so systemd restarts us fresh (the watchdog handles the silent-drop case).
    log.error("SinricPro connection ended — exiting for a clean restart")
    raise SystemExit(1)


if __name__ == "__main__":
    main()
