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

Command sending (MQTT over AWS IoT) is NOT wired up yet — the p12 password and
cloud payload schema still need a traffic capture. See PROTOCOL.md §7e.
"""
from flask import Flask, request, jsonify, send_from_directory
import requests, os, sys

# cloud MQTT control (mutual-TLS to AWS IoT); lives one dir up
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import helium_cloud

API = "https://o7sbv8y912.execute-api.ap-south-1.amazonaws.com/dev"
# the 'hoags' backend (different service) — where cloud devices actually live
HOAGS = "https://tz1z01inlb.execute-api.ap-south-1.amazonaws.com/hoags"
app = Flask(__name__, static_folder=".", static_url_path="")

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


# ---- cloud MQTT control (AWS IoT mutual-TLS; no account token needed) ----

@app.get("/api/ac/state")
def ac_state():
    """Read the AC's live state over cloud MQTT."""
    try:
        return jsonify(helium_cloud.read_state())
    except Exception as e:
        return jsonify({"error": str(e)}), 502


@app.post("/api/ac/command")
def ac_command():
    """Send an AC command over cloud MQTT.

    Body (one of):
      {"temperature": 23}
      {"power": true|false}
      {"mode": "cool"|"heat"|...}
      {"fan": "auto"|"low"|"medium"|"high"}
      {"turbo": true|false}
    """
    body = request.json or {}
    try:
        if "temperature" in body:
            payload = helium_cloud.temperature_payload(int(body["temperature"]))
        elif "power" in body:
            payload = helium_cloud.power_payload(bool(body["power"]))
        elif "mode" in body:
            payload = helium_cloud.mode_payload(str(body["mode"]))
        elif "fan" in body:
            payload = helium_cloud.fan_payload(str(body["fan"]))
        elif "turbo" in body:
            payload = helium_cloud.turbo_payload(bool(body["turbo"]))
        else:
            return jsonify({"error": "no known command field"}), 400
    except (KeyError, ValueError) as e:
        return jsonify({"error": f"bad command: {e}"}), 400

    try:
        helium_cloud.publish_command(payload)
        return jsonify({"ok": True, "payload": payload})
    except Exception as e:
        return jsonify({"error": str(e)}), 502


@app.get("/")
def index():
    return send_from_directory(".", "index.html")


if __name__ == "__main__":
    print("Helium panel on http://localhost:5055")
    app.run(port=5055, debug=False)
