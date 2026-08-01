#!/usr/bin/env python3
"""
Helium AC — BLE transport bridge for the Flask server.

bleak is async and the AC accepts a single BLE central, so we own exactly one
connection from one background thread running a dedicated asyncio loop. Flask
handlers (sync, multi-threaded) call in via asyncio.run_coroutine_threadsafe.

BLE and cloud take byte-identical payloads (PROTOCOL §7j), so callers build the
hex with helium_cloud's builders and hand it to send() here.
"""
import asyncio, os, sys, threading

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from helium import Helium, PASSKEY, DP_NAMES

# same DP map used for the cloud state shape, so both transports report alike
STATE_NAMES = {0x01: "power", 0x02: "setpoint_C", 0x04: "mode", 0x05: "fan",
               0x1C: "power_W", 0x6A: "room_temp_C", 0x67: "turbo",
               0x6E: "vertical_swing", 0x79: "passkey_ack"}


class BleBridge:
    def __init__(self):
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._run_loop, daemon=True,
                                        name="ble-loop")
        self._thread.start()
        self._lock = threading.Lock()   # serialize connect/disconnect
        self.ac = None

    def _run_loop(self):
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()

    def _call(self, coro, timeout=60):
        return asyncio.run_coroutine_threadsafe(coro, self._loop).result(timeout)

    @property
    def connected(self):
        return bool(self.ac and self.ac.client and self.ac.client.is_connected)

    def connect(self, passkey=PASSKEY):
        """Scan, connect and authenticate. Idempotent."""
        with self._lock:
            if self.connected:
                return {"connected": True, "already": True}
            ac = Helium()
            self._call(ac.connect(), timeout=60)
            # login() waits for the 0x79 passkey ack, which the unit only re-sends
            # on a fresh session — a False here does NOT mean commands are refused.
            authed = self._call(ac.login(passkey), timeout=30)
            self.ac = ac
            # the passkey packet also provokes the full DP dump; give it a moment
            self._call(asyncio.sleep(2), timeout=10)
            return {"connected": True, "authed": authed, "datapoints": len(ac.state)}

    def disconnect(self):
        with self._lock:
            if not self.ac:
                return {"connected": False}
            self._call(self.ac.close(), timeout=30)
            self.ac = None
            return {"connected": False}

    def send(self, hex_payload: str):
        """Write a payload (same hex the cloud builders emit) over BLE."""
        if not self.connected:
            self.connect()
        self._call(self.ac.send(bytes.fromhex(hex_payload)), timeout=30)
        return hex_payload

    def read_state(self):
        """Snapshot ac.state (int DP keys) into the label-keyed cloud shape.

        helium.py's notify parser trusts the frame's own length field, so a DP
        whose frame carries trailing bytes decodes as an absurd integer (seen
        live: fan = 13002342400, while a simultaneous cloud read reported no fan
        DP at all). Drop values too wide for the DP rather than report them —
        the panel showing "—" beats it showing a confident wrong number.
        """
        if not self.connected:
            self.connect()
        out = {}
        for dp, val in sorted(self.ac.state.items()):
            if dp != 0x1C and val > 0xFFFF:   # DP1C (power draw) is a wide counter
                continue
            out[STATE_NAMES.get(dp, hex(dp))] = val
        return out


_bridge = None
_bridge_lock = threading.Lock()


def bridge() -> BleBridge:
    """Lazily create the singleton bridge (no BLE thread until BLE is used)."""
    global _bridge
    with _bridge_lock:
        if _bridge is None:
            _bridge = BleBridge()
        return _bridge


def status():
    return {"connected": bool(_bridge and _bridge.connected)}
