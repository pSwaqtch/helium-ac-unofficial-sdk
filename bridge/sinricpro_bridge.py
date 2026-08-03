#!/usr/bin/env python3
"""
SinricPro → Helium AC bridge.

Lets Google Assistant control the AC ("Hey Google, turn on AC") without Nabu Casa,
Home Assistant, or exposing any inbound port. SinricPro publishes a free Google
Home (and Alexa) integration; this process holds an *outbound* websocket to their
cloud, receives the voice-triggered commands, and translates them into the same
cloud MQTT payloads the rest of this project sends.

    "Hey Google…" → Google Home → SinricPro cloud → (this bridge) → AWS IoT → AC

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

DP_ROOM_TEMP = 0x6A                  # room/indoor temperature °C (PROTOCOL §5e)
REPORT_SEC = 60                      # push current temp to Google this often
REFRESH_SEC = 180                    # re-read room temp this often (non-actuating)
WATCHDOG_SEC = 20                    # how often to check the SinricPro socket
WATCHDOG_GRACE = 45                  # let the first connection settle before watching

# last values we told the AC, so we can echo sensible state back to Google
_state = {"power": "Off", "setpoint": 24, "mode": DEFAULT_MODE}

# latest room temperature, updated from ACKs and periodic reads; read by the
# reporter task. `None` until we get a real value (so we never report a fake 0).
_cache = {"room_temp": None}
_cache_lock = threading.Lock()

# set once the SinricPro client exists, so the async reporter can raise events
_client = None


def _plausible_temp(t):
    return t is not None and 0 < t < 60


def _cache_room_temp(t):
    if _plausible_temp(t):
        with _cache_lock:
            _cache["room_temp"] = t


# ---------------------------------------------------------------------------
# Helium I/O runs on ONE dedicated thread that owns the MQTT client, so the
# asyncio event loop is never blocked by a (re)connect and MQTT access is
# serialized. Commands are QoS-0 fire-and-forget — the device sends no reliable
# ack — so callbacks enqueue and report success optimistically.
# ---------------------------------------------------------------------------
_q: "queue.Queue[str]" = queue.Queue()


def _on_ack(_topic, text):
    """Cache the room temp out of any DP dump the device pushes."""
    _cache_room_temp(h.parse_ack(text).get(DP_ROOM_TEMP))


def _worker():
    cli = None
    while True:
        payload = _q.get()
        for attempt in (1, 2):
            try:
                if cli is None:
                    log.info("connecting to AWS IoT…")
                    cli = h.connect(on_ack=_on_ack, timeout=20)
                h.publish_command(payload, cli=cli)
                break
            except Exception as e:  # noqa: BLE001 — reconnect on any failure
                log.warning("publish failed (attempt %d/2): %s", attempt, e)
                try:
                    if cli:
                        cli.loop_stop()
                        cli.disconnect()
                except Exception:
                    pass
                cli = None
        else:
            log.error("gave up on payload %s", payload)


def send(payload: str):
    """Queue one already-built hex payload for delivery to the AC."""
    _q.put(payload)


def _clamp_temp(t) -> int:
    return max(TEMP_MIN, min(TEMP_MAX, int(round(float(t)))))


def _temp_refresher():
    """Periodically read the AC's room temp so Google's 'current temperature'
    stays fresh even when no commands are being sent. read_state() opens its own
    short-lived connection and sends no command — it doesn't actuate the unit."""
    while True:
        try:
            rt = h.read_state().get("room_temp_C")
            if _plausible_temp(rt):
                _cache_room_temp(rt)
                log.info("room temp refreshed: %d C", rt)
        except Exception as e:  # noqa: BLE001 — never let the refresher die
            log.debug("temp refresh failed: %s", e)
        time.sleep(REFRESH_SEC)


async def _report_current_temperature():
    """SinricPro event_callbacks entrypoint: push cached room temp to Google on
    an interval. The AC has no humidity sensor, so humidity is reported as 0."""
    while True:
        await asyncio.sleep(REPORT_SEC)
        with _cache_lock:
            rt = _cache["room_temp"]
        if rt is None or _client is None:
            continue
        try:
            _client.event_handler.raise_event(
                DEVICE_ID,
                SinricProConstants.CURRENT_TEMPERATURE,
                data={"temperature": float(rt), "humidity": 0.0},
            )
            log.info("reported current temp %d C to Google", rt)
        except Exception as e:  # noqa: BLE001
            log.warning("temp report failed: %s", e)


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
    return True, state


def on_target_temperature(device_id, temperature):
    """Absolute setpoint, e.g. "set AC to 24"."""
    t = _clamp_temp(temperature)
    log.info("setpoint -> %d C", t)
    send(h.temperature_payload(t))
    _state["setpoint"] = t
    return True, t


def on_set_thermostat_mode(device_id, mode):
    """mode is COOL / HEAT / AUTO / OFF (Google's thermostat modes)."""
    mode = (mode or "").upper()
    log.info("mode -> %s", mode)
    if mode == SinricProConstants.THERMOSTAT_MODE_OFF:
        send(h.power_payload(False))
        _state["power"] = "Off"
        return True, mode
    # COOL / HEAT / AUTO → make sure it's on, then set the operating mode
    hmode = "heat" if mode == SinricProConstants.THERMOSTAT_MODE_HEAT else "cool"
    send(h.power_payload(True))
    send(h.mode_payload(hmode))
    _state["power"] = "On"
    _state["mode"] = hmode
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

    # start the MQTT worker and the room-temp refresher before accepting commands
    threading.Thread(target=_worker, name="helium-mqtt", daemon=True).start()
    threading.Thread(target=_temp_refresher, name="helium-temp", daemon=True).start()
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
