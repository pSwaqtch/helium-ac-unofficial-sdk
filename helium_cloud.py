#!/usr/bin/env python3
"""
Helium AC — cloud (AWS IoT MQTT) control.

Reproduces the vendor app's HeliumCloudMQTTModule: mutual-TLS to AWS IoT with the
shipped client cert (AWSiOT.p12, password "1234" — captured at runtime via Frida)
and publishes the same buildPacket hex payload the app sends.

Payload is byte-identical to the BLE temperature frame (PROTOCOL §5g/§7g):
  25-byte header (cmdId=1003 AC_CTRL, seq=1, total_level=2, level=02 00 00 00 00,
  totalSize=1) + 1-byte celsius, rendered as lowercase hex text.

Verified inputs (see memory: helium-cloud-mqtt-secrets):
  host  = a198fgj6igmrrt-ats.iot.ap-south-1.amazonaws.com : 8883
  topic = hoags/Helium/ac/HELM0000015HMKP1/<your-device-macid>/hoagsUIControl
  ack   = .../hoagsUIControlAck
"""
import os, ssl, time, tempfile, struct, warnings
import paho.mqtt.client as mqtt
from cryptography.hazmat.primitives.serialization import pkcs12, Encoding, PrivateFormat, NoEncryption

# AWSiOT.p12 is BER-encoded; cryptography parses it fine but warns. Silence it.
warnings.filterwarnings("ignore", message="PKCS#12 bundle could not be parsed as DER")

HERE = os.path.dirname(os.path.abspath(__file__))
P12_PATH = os.path.join(HERE, "apk/assets/AWSiOT.p12")
CA_PATH  = os.path.join(HERE, "apk/assets/AmazonRootCA1.pem")
P12_PASSWORD = b"1234"

HOST = "a198fgj6igmrrt-ats.iot.ap-south-1.amazonaws.com"
PORT = 8883
MAC  = "<your-device-macid>"
BASE_TOPIC = f"hoags/Helium/ac/HELM0000015HMKP1/{MAC}"
PUB_TOPIC  = f"{BASE_TOPIC}/hoagsUIControl"
ACK_TOPIC  = f"{BASE_TOPIC}/hoagsUIControlAck"


def _client_id():
    return f"pyhelium_{int(time.time()*1000)}"


def build_packet(cmd_id: int, payload: bytes, seq: int = 1, total_level: int = 2,
                 level: bytes = b"\x02\x00\x00\x00\x00") -> str:
    """Serialize the app's 25-byte-header packet, return lowercase hex string.

    Matches the captured cloud payload exactly (checksum sent as 0, params 0)."""
    assert len(level) == 5
    hdr = bytearray(25)
    hdr[0] = 0xFF                                    # header
    struct.pack_into(">H", hdr, 1, cmd_id)           # cmdId
    struct.pack_into(">H", hdr, 3, len(payload))     # len
    struct.pack_into(">H", hdr, 5, seq)              # seqNum
    struct.pack_into(">I", hdr, 7, 0)                # checksum (app sends 0)
    hdr[11] = total_level                            # total_level
    hdr[12:17] = level                               # level
    struct.pack_into(">I", hdr, 17, len(payload))    # totalSize
    struct.pack_into(">I", hdr, 21, 0)               # params
    return (bytes(hdr) + payload).hex()


def _ctrl(sub: int, data: bytes, level: bytes = None) -> str:
    """AC_CTRL (1003) command. sub -> level[0]; data is the DP payload bytes.

    Mirrors the app's buildXxxPacket family (decompiled): the common serializer
    is called with level=[sub,0,0,0,0] and a data array. len/totalSize follow the
    data length. A few commands override level (timer sets level[1]=1)."""
    if level is None:
        level = bytes([sub, 0, 0, 0, 0])
    return build_packet(1003, data, level=level)


# --- the full command family (verbatim polarity from decompiled buildXxxPacket) ---
# NOTE bool polarity differs per command; do NOT assume a single convention.

FAN_SPEEDS = {"auto": 0, "low": 1, "medium": 2, "high": 3}

def temperature_payload(celsius: int) -> str:
    return _ctrl(2, bytes([celsius & 0xFF]))                      # sub 2

def power_payload(on: bool) -> str:
    return _ctrl(0, bytes([0 if on else 1]))                     # sub 0, INVERTED (on->0)

def fan_payload(speed: str) -> str:
    return _ctrl(1, bytes([FAN_SPEEDS[speed]]))                  # sub 1

def mode_payload(mode: str) -> str:
    return _ctrl(3, bytes([1 if mode == "cool" else 0]))        # sub 3, cool->1

def vertical_swing_payload(on: bool) -> str:
    return _ctrl(4, bytes([1 if on else 0]))                    # sub 4, on->1

def turbo_payload(on: bool) -> str:
    return _ctrl(5, bytes([0 if on else 1]))                    # sub 5, INVERTED (on->0)

def sleep_payload(on: bool) -> str:
    return _ctrl(6, bytes([1 if on else 0]))                    # sub 6, on->1

def display_payload(on: bool) -> str:
    return _ctrl(10, bytes([1 if on else 0]))                   # sub 10, on->1

def convertible_payload(value: int) -> str:
    return _ctrl(17, bytes([value & 0xFF]))                     # sub 17, raw byte

def silent_payload(on: bool) -> str:
    return _ctrl(20, bytes([0 if on else 1]))                   # sub 20, INVERTED (on->0)

def horizontal_swing_payload(on: bool) -> str:
    # sub 21, TWO-byte data [0, on?1:0]  (app: r2=[0]; r2[1]=value)
    return _ctrl(21, bytes([0, 1 if on else 0]))

def timer_payload(minutes: int, on: bool) -> str:
    # app: level=[18,1,0,0,0] if on else [19,1,0,0,0]; data=[minutes>>8 & 0xFF, minutes & 0xFF]
    sub = 18 if on else 19
    data = bytes([(minutes >> 8) & 0xFF, minutes & 0xFF])
    return _ctrl(sub, data, level=bytes([sub, 1, 0, 0, 0]))


def _extract_pem():
    """Unlock the p12 and write cert+key to a temp PEM pair for paho tls_set."""
    with open(P12_PATH, "rb") as f:
        key, cert, extra = pkcs12.load_key_and_certificates(f.read(), P12_PASSWORD)
    certf = tempfile.NamedTemporaryFile(delete=False, suffix=".crt.pem")
    keyf  = tempfile.NamedTemporaryFile(delete=False, suffix=".key.pem")
    certf.write(cert.public_bytes(Encoding.PEM))
    for c in (extra or []):
        certf.write(c.public_bytes(Encoding.PEM))
    keyf.write(key.private_bytes(Encoding.PEM, PrivateFormat.TraditionalOpenSSL, NoEncryption()))
    certf.flush(); keyf.flush(); certf.close(); keyf.close()
    return certf.name, keyf.name


def connect(on_ack=None, timeout=10):
    """Connect to AWS IoT with mutual-TLS. Returns a connected paho client."""
    certfile, keyfile = _extract_pem()
    cli = mqtt.Client(client_id=_client_id(), protocol=mqtt.MQTTv311)
    cli.tls_set(ca_certs=CA_PATH, certfile=certfile, keyfile=keyfile,
                cert_reqs=ssl.CERT_REQUIRED, tls_version=ssl.PROTOCOL_TLS_CLIENT)

    state = {"connected": False, "rc": None}

    def _on_connect(c, u, flags, rc, *a):
        state["connected"] = (rc == 0); state["rc"] = rc
        if rc == 0:
            c.subscribe(ACK_TOPIC, qos=0)  # app subscribes at QoS 0

    def _on_message(c, u, msg):
        text = msg.payload.decode("utf-8", "replace")
        print(f"[ack] {msg.topic}: {text}")
        if on_ack:
            on_ack(msg.topic, text)

    cli.on_connect = _on_connect
    cli.on_message = _on_message
    cli.connect(HOST, PORT, keepalive=60)
    cli.loop_start()
    deadline = time.time() + timeout
    while time.time() < deadline and state["rc"] is None:
        time.sleep(0.05)
    if not state["connected"]:
        cli.loop_stop()
        raise RuntimeError(f"MQTT connect failed, rc={state['rc']}")
    # clean up temp PEMs now that the TLS context holds them open
    for p in (certfile, keyfile):
        try: os.unlink(p)
        except OSError: pass
    return cli


def publish_command(hex_payload: str, wait_ack=3.0, cli=None):
    """Publish a buildPacket hex payload to the control topic.

    CRITICAL: the app hex-DECODES the payload string to raw bytes before
    publishing (HeliumCloudMQTTModule.publish: if all-hex & even-length ->
    binary), and sends at QoS 0. We must do the same — sending the hex text
    itself does NOT actuate the AC.
    """
    raw = bytes.fromhex(hex_payload)
    own = cli is None
    if own:
        cli = connect()
    print(f"[pub] {PUB_TOPIC}\n      {hex_payload}  ({len(raw)} raw bytes, qos0)")
    info = cli.publish(PUB_TOPIC, raw, qos=0)   # raw bytes, QoS 0 — matches app
    info.wait_for_publish(timeout=5)
    if own:
        time.sleep(wait_ack)
        cli.loop_stop(); cli.disconnect()
    return hex_payload


def set_temperature(celsius: int, wait_ack=3.0):
    """One-shot: connect, publish a temperature command, wait briefly for ack."""
    return publish_command(temperature_payload(celsius), wait_ack=wait_ack)


# --- state read (parse the Tuya DP frames the device pushes on the ack topic) ---
import re as _re

DP_NAMES = {0x01: "power", 0x02: "setpoint_C", 0x1C: "power_W",
            0x6A: "room_temp_C"}


def parse_ack(text: str) -> dict:
    """Extract DP id->value from a 'Poll:0:<concatenated 55aa frames>' ack."""
    out = {}
    for m in _re.finditer(r"55aa0307[0-9a-f]{4}([0-9a-f]{2})02([0-9a-f]{4})([0-9a-f]{8})", text):
        dp = int(m.group(1), 16)
        out[dp] = int(m.group(3), 16)
    # 1-byte bool/enum DPs (type 01/04, len 0001)
    for m in _re.finditer(r"55aa0307[0-9a-f]{4}([0-9a-f]{2})0[14]0001([0-9a-f]{2})", text):
        dp = int(m.group(1), 16)
        out.setdefault(dp, int(m.group(2), 16))
    return out


def read_state(timeout=6.0, attempts=3) -> dict:
    """Connect and return the AC's current state (named DPs) from the ack dump.

    The device pushes its full Poll dump only on some connects, so retry across a
    few fresh connections (nudging it with a re-subscribe) until DP2 appears.
    """
    latest = {}

    def on_ack(topic, text):
        latest.update(parse_ack(text))

    for _ in range(attempts):
        cli = connect(on_ack=on_ack, timeout=15)
        deadline = time.time() + timeout
        while time.time() < deadline and 0x02 not in latest:
            time.sleep(0.1)
        cli.loop_stop(); cli.disconnect()
        if 0x02 in latest:
            break
    return {DP_NAMES.get(k, hex(k)): v for k, v in sorted(latest.items())}


if __name__ == "__main__":
    import sys
    t = int(sys.argv[1]) if len(sys.argv) > 1 else 24
    set_temperature(t)
