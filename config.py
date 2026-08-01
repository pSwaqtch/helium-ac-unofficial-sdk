#!/usr/bin/env python3
"""
Deployment config, read from the environment.

Everything device- or account-specific lives here rather than in the modules,
so the source stays publishable and you configure your own unit with a `.env`
(see `.env.example`). `.env` is gitignored.

Nothing here is secret in the cryptographic sense — the p12 password and BLE
passkey are vendor constants recovered by reverse engineering (PROTOCOL §7i),
and the defaults below are those constants. What you must supply is your own
device MAC, because it addresses your specific unit.
"""
import os

HERE = os.path.dirname(os.path.abspath(__file__))


def _load_dotenv(path=os.path.join(HERE, ".env")):
    """Minimal .env loader — no dependency, no override of a real env var."""
    try:
        with open(path) as fh:
            for line in fh:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
    except FileNotFoundError:
        pass


_load_dotenv()


def _req(name, default=None):
    """Fetch a setting; explain how to fix it if it's missing and has no default."""
    v = os.environ.get(name, default)
    if v in (None, ""):
        raise SystemExit(
            f"{name} is not set.\n"
            f"Copy .env.example to .env and fill it in, or export {name}=…"
        )
    return v


# ---- your device (no safe default — this addresses your unit) ----
# lowercase hex, no separators, e.g. from the hoags device list `macid` field
DEVICE_MAC = _req("HELIUM_DEVICE_MAC")
# product model in the MQTT topic path
DEVICE_MODEL = os.environ.get("HELIUM_DEVICE_MODEL", "HELM0000015HMKP1")
# substring used to spot the AC in a BLE scan; defaults to the MAC's last 4 hex
BLE_NAME_MATCH = os.environ.get("HELIUM_BLE_NAME_MATCH") or DEVICE_MAC[-4:]

# ---- vendor constants (recovered; defaults are correct for stock firmware) ----
BLE_PASSKEY = os.environ.get("HELIUM_BLE_PASSKEY", "1111")
P12_PASSWORD = os.environ.get("HELIUM_P12_PASSWORD", "1234").encode()

# ---- cloud endpoints ----
MQTT_HOST = os.environ.get(
    "HELIUM_MQTT_HOST", "a198fgj6igmrrt-ats.iot.ap-south-1.amazonaws.com"
)
MQTT_PORT = int(os.environ.get("HELIUM_MQTT_PORT", "8883"))
API_BASE = os.environ.get(
    "HELIUM_API_BASE", "https://o7sbv8y912.execute-api.ap-south-1.amazonaws.com/dev"
)
HOAGS_BASE = os.environ.get(
    "HELIUM_HOAGS_BASE", "https://tz1z01inlb.execute-api.ap-south-1.amazonaws.com/hoags"
)

# ---- credential files (gitignored; extracted from the vendor APK) ----
P12_PATH = os.environ.get("HELIUM_P12_PATH", os.path.join(HERE, "apk/assets/AWSiOT.p12"))
CA_PATH = os.environ.get("HELIUM_CA_PATH", os.path.join(HERE, "apk/assets/AmazonRootCA1.pem"))

# ---- derived ----
BASE_TOPIC = f"hoags/Helium/ac/{DEVICE_MODEL}/{DEVICE_MAC}"
PUB_TOPIC = f"{BASE_TOPIC}/hoagsUIControl"
ACK_TOPIC = f"{BASE_TOPIC}/hoagsUIControlAck"
