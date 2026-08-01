#!/usr/bin/env python3
"""
Helium Air — self-hosted control panel backend.

A thin proxy to Helium's own cloud API, reproducing the mobile app's auth flow so
we can log in with a phone OTP and read device state without the Android app.

Endpoints reproduced (verified live):
  POST /auth/send-otp    {phone, isSignUp}
  POST /auth/verify-otp  {phone, otp} -> {tokens:{accessToken,...}, ...}
  GET  /auth/me          Bearer -> account
  GET  /devices          Bearer -> [device]
  GET  /devices/{id}/status  Bearer -> status   (path guessed from LOG_STATUS route)

Command sending works over both transports (cloud MQTT and BLE) — see §7j/§7k.
Endpoints and device identity come from `config` (a `.env` file); see
`.env.example`.
"""
from flask import Flask, request, jsonify, send_from_directory
import requests, os, sys

# cloud MQTT control (mutual-TLS to AWS IoT); lives one dir up
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config
import helium_cloud
import ble_bridge

API = config.API_BASE
# the 'hoags' backend (different service) — where cloud devices actually live
HOAGS = config.HOAGS_BASE
# the built SPA (vite `npm run build` in web/); assets are hashed under dist/assets
DIST = os.path.join(os.path.dirname(os.path.abspath(__file__)), "dist")
app = Flask(__name__, static_folder=DIST, static_url_path="")

# in-memory token store (single user, local use)
SESSION = {"access": None, "id": None, "refresh": None, "phone": None, "hoagsUserId": None}
# which token the API Gateway authorizer accepts; determined at verify time
AUTH_TOKEN_KEY = "id"  # Cognito authorizers typically want the idToken


def api(method, path, token=None, base=API, **kw):
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    r = requests.request(method, base + path, headers=headers, timeout=15, **kw)
    try:
        body = r.json()
    except Exception:
        body = {"raw": r.text}
    return r.status_code, body


@app.post("/api/send-otp")
def send_otp():
    phone = request.json["phone"]
    code, body = api("POST", "/auth/send-otp", json={"phone": phone, "isSignUp": False})
    SESSION["phone"] = phone
    return jsonify(body), code


@app.post("/api/verify-otp")
def verify_otp():
    phone = request.json.get("phone") or SESSION["phone"]
    otp = request.json["otp"]
    code, body = api("POST", "/auth/verify-otp", json={"phone": phone, "otp": otp})
    if code == 200:
        toks = body.get("tokens", {})
        SESSION["access"] = toks.get("accessToken")
        SESSION["id"] = toks.get("idToken")
        SESSION["refresh"] = toks.get("refreshToken")
    return jsonify(body), code


def tok():
    return SESSION[AUTH_TOKEN_KEY]


def extract_hoags_id(body):
    u = body.get("user", body)
    return u.get("hoagsUserId")


@app.get("/api/me")
def me():
    code, body = api("GET", "/auth/me", token=tok())
    if code == 200:
        SESSION["hoagsUserId"] = extract_hoags_id(body)
    return jsonify(body), code


@app.get("/api/devices")
def devices():
    # primary backend
    code, body = api("GET", "/devices", token=tok())
    return jsonify(body), code


@app.get("/api/hoags-devices")
def hoags_devices():
    """Cloud devices from the hoags backend, keyed by hoagsUserId."""
    uid = SESSION.get("hoagsUserId")
    if not uid:
        c, b = api("GET", "/auth/me", token=tok())
        uid = extract_hoags_id(b)
        SESSION["hoagsUserId"] = uid
    code, body = api("GET", f"/user/devices?user={uid}", token=tok(), base=HOAGS)
    return jsonify({"hoagsUserId": uid, "resp": body}), code


@app.get("/api/devices/<did>/status")
def device_status(did):
    code, body = api("GET", f"/devices/{did}/status", token=SESSION["access"])
    return jsonify(body), code


@app.get("/api/session")
def session():
    return jsonify({"loggedIn": bool(SESSION["access"]), "phone": SESSION["phone"]})


# ---- AC control over either transport (cloud MQTT / BLE) ----
# Both transports take the SAME payload bytes (PROTOCOL §7j), so every command is
# built once with helium_cloud's builders and then routed by `transport`.

COMMANDS = {
    "temperature":     lambda v: helium_cloud.temperature_payload(int(v)),
    "power":           lambda v: helium_cloud.power_payload(bool(v)),
    "fan":             lambda v: helium_cloud.fan_payload(str(v)),
    "mode":            lambda v: helium_cloud.mode_payload(str(v)),
    "verticalSwing":   lambda v: helium_cloud.vertical_swing_payload(bool(v)),
    "turbo":           lambda v: helium_cloud.turbo_payload(bool(v)),
    "sleep":           lambda v: helium_cloud.sleep_payload(bool(v)),
    "display":         lambda v: helium_cloud.display_payload(bool(v)),
    "convertible":     lambda v: helium_cloud.convertible_payload(int(v)),
    "silent":          lambda v: helium_cloud.silent_payload(bool(v)),
    "horizontalSwing": lambda v: helium_cloud.horizontal_swing_payload(bool(v)),
    # timer takes {"timer": {"minutes": 30, "on": true}}
    "timer":           lambda v: helium_cloud.timer_payload(int(v["minutes"]),
                                                            bool(v.get("on", True))),
}


def transport_of(body=None):
    """`transport` from the query string or the JSON body; defaults to cloud."""
    t = request.args.get("transport") or (body or {}).get("transport") or "cloud"
    if t not in ("ble", "cloud"):
        raise ValueError(f"unknown transport {t!r}")
    return t


@app.get("/api/ac/state")
def ac_state():
    """Read the AC's live state over the selected transport."""
    try:
        t = transport_of()
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    try:
        state = ble_bridge.bridge().read_state() if t == "ble" else helium_cloud.read_state()
        return jsonify({"transport": t, "state": state})
    except BaseException as e:   # SystemExit from helium.connect() isn't an Exception
        app.logger.exception("state read failed (%s)", t)
        return jsonify({"error": str(e) or type(e).__name__}), 502


@app.post("/api/ac/command")
def ac_command():
    """Send an AC command over BLE or cloud.

    Body: exactly one of COMMANDS' keys, e.g. {"temperature": 23},
    {"power": true}, {"fan": "high"}, {"timer": {"minutes": 30, "on": true}}.
    Transport via ?transport=ble|cloud or a "transport" field (default cloud).
    """
    body = request.json or {}
    try:
        t = transport_of(body)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400

    field = next((k for k in COMMANDS if k in body), None)
    if field is None:
        return jsonify({"error": "no known command field"}), 400
    try:
        payload = COMMANDS[field](body[field])
    except (KeyError, TypeError, ValueError) as e:
        return jsonify({"error": f"bad command: {e}"}), 400

    try:
        if t == "ble":
            ble_bridge.bridge().send(payload)
        else:
            helium_cloud.publish_command(payload)
        return jsonify({"ok": True, "transport": t, "command": field, "payload": payload})
    except BaseException as e:   # SystemExit from helium.connect() isn't an Exception
        app.logger.exception("command failed (%s/%s)", t, field)
        return jsonify({"error": str(e) or type(e).__name__, "payload": payload}), 502


# ---- BLE link management (single central; connect lazily, hold the link) ----

@app.get("/api/ble/status")
def ble_status():
    return jsonify(ble_bridge.status())


@app.post("/api/ble/connect")
def ble_connect():
    try:
        return jsonify(ble_bridge.bridge().connect())
    except BaseException as e:
        # helium.connect() raises SystemExit when the AC isn't advertising, and
        # str(SystemExit) is "" — report the type so the error is never blank.
        app.logger.exception("BLE connect failed")
        return jsonify({"error": str(e) or type(e).__name__}), 502


@app.post("/api/ble/disconnect")
def ble_disconnect():
    try:
        return jsonify(ble_bridge.bridge().disconnect())
    except Exception as e:
        return jsonify({"error": str(e)}), 502


@app.get("/")
def index():
    return send_from_directory(DIST, "index.html")


@app.errorhandler(404)
def spa_fallback(_e):
    """Unknown non-API paths fall through to the SPA."""
    if request.path.startswith("/api/"):
        return jsonify({"error": "not found"}), 404
    return send_from_directory(DIST, "index.html")


if __name__ == "__main__":
    print("Helium panel on http://localhost:5055")
    app.run(port=5055, debug=False)
