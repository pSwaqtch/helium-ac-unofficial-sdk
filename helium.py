#!/usr/bin/env python3
"""
Helium AC BLE client.

Protocol recovered from the Helium Android app (Hermes bytecode). See PROTOCOL.md.

Wire format (from Packet.serialize() in the app bundle) — 25-byte header + payload:

    off  0  u8    header        always 0xFF
    off  1  u16BE cmdId         600=BLE_PASSKEY, 1003=AC_CTRL, ...
    off  3  u16BE len           payload length
    off  5  u16BE seqNum
    off  7  u32BE checksum
    off 11  u8    total_level
    off 12  [5]   level         5 zero bytes
    off 17  u32BE totalSize
    off 21  u32BE params
    off 25  ...   payload

The serialized buffer is hex-encoded to an ASCII string, and that *text* is what
is written to b002 (the app base64s it only because react-native-ble-plx requires
base64 for the transport).

The MCU ignores all AC_CTRL commands until the session is authenticated with the
4-digit passkey (this unit: 1111; factory-fresh units use 0000).
"""
import asyncio, sys, re
from bleak import BleakScanner, BleakClient

B002 = "0000b002-0000-1000-8000-00805f9b34fb"
B003 = "0000b003-0000-1000-8000-00805f9b34fb"

PASSKEY = "1111"

CMD_BLE_PASSKEY   = 600
CMD_AC_CTRL       = 1003
CMD_STATUS_DATA   = 500

# AC_CTRL sub-command ids (header byte 0 of the 5-byte AC_CTRL header)
AC_POWER, AC_FAN, AC_TEMP, AC_MODE, AC_VSWING, AC_TURBO, AC_SLEEP = 0,1,2,3,4,5,6

MODES = {"cool":0, "dry":1, "fan":2, "heat":3, "auto":4}

# datapoints seen on the Poll: stream
DP_NAMES = {0x02:"setpoint_C", 0x1C:"power_W", 0x6A:"room_temp_C", 0x79:"passkey_ack"}


def packet(cmd_id, payload: bytes, seq=1, params=0, total_level=2) -> bytes:
    """
    Packet.serialize(), with field values taken from a real app session
    (btsnoop capture) rather than from static analysis:

        seqNum      = 1
        level       = 02 00 00 00 00     (NOT all zeros)
        total_level = 1 for BLE_PASSKEY, 2 for AC_CTRL
    """
    b = bytearray(25 + len(payload))
    b[0]      = 0xFF
    b[1:3]    = cmd_id.to_bytes(2, "big")
    b[3:5]    = len(payload).to_bytes(2, "big")
    b[5:7]    = seq.to_bytes(2, "big")
    b[7:11]   = (0).to_bytes(4, "big")          # checksum (app sends 0)
    b[11]     = total_level
    b[12:17]  = bytes([0x02, 0, 0, 0, 0])       # level
    b[17:21]  = len(payload).to_bytes(4, "big") # totalSize
    b[21:25]  = params.to_bytes(4, "big")
    b[25:]    = payload
    return bytes(b)


# AC_CTRL payloads observed on the wire are a BARE value byte — the 5-byte
# sub-header from buildPacket() is not present in the BLE path.
def p_temp(c):     return packet(CMD_AC_CTRL, bytes([c & 0xFF]))
def p_passkey(pk): return packet(CMD_BLE_PASSKEY, pk.encode("utf-8"), total_level=1)


class Helium:
    def __init__(self, name_match="7f93"):
        self.name_match = name_match
        self.client = None
        self.state = {}
        self.authed = asyncio.Event()
        self.verbose = True

    def _on_notify(self, _, data):
        raw = bytes(data).rstrip(b"\x00").decode("ascii", "replace")
        m = re.match(r"Poll:\d+:([0-9a-fA-F]+)", raw)
        if not m:
            if self.verbose and "Diag" in raw and "Publishing" not in raw and "->1001" not in raw:
                print(f"   [diag] {raw[:90]}")
            return
        b = bytes.fromhex(m.group(1))
        if len(b) >= 10 and b[0] == 0x55 and b[1] == 0xAA and b[3] == 0x07:
            dpid = b[6]
            dlen = int.from_bytes(b[8:10], "big")
            val  = int.from_bytes(b[10:10+dlen], "big")
            prev = self.state.get(dpid)
            self.state[dpid] = val
            if dpid == 0x79:
                self.authed.set()
            if prev != val:
                print(f"   [state] {DP_NAMES.get(dpid, f'DP0x{dpid:02x}')} = {val}")

    async def connect(self):
        print(f"scanning for {self.name_match} ...")
        dev = None
        def cb(d, adv):
            nonlocal dev
            n = d.name or adv.local_name or ""
            if self.name_match in n.lower() and dev is None:
                dev = d
        s = BleakScanner(cb); await s.start()
        for _ in range(25):
            await asyncio.sleep(1)
            if dev: break
        await s.stop()
        if not dev:
            raise SystemExit("AC not advertising — is the phone app connected to it?")
        self.client = BleakClient(dev, timeout=25.0)
        await self.client.connect()
        await self.client.start_notify(B003, self._on_notify)
        print(f"connected to {dev.name}")

    async def send(self, pkt: bytes):
        # raw bytes, ATT Write Request (with response) — matches the capture
        await self.client.write_gatt_char(B002, pkt, response=True)

    async def login(self, passkey=PASSKEY, timeout=8):
        print(f"authenticating with passkey {passkey} ...")
        await self.send(p_passkey(passkey))
        try:
            await asyncio.wait_for(self.authed.wait(), timeout=timeout)
            print("   AUTH OK (DPID 0x79 ack)")
            return True
        except asyncio.TimeoutError:
            print("   no passkey ack")
            return False

    async def set_temp(self, c, confirm=True, timeout=15):
        """Set the setpoint. Returns True only if the device reports the new value."""
        before = self.state.get(0x02)
        print(f"-> set temperature {c}C (current {before})")
        await self.send(p_temp(c))
        if not confirm:
            return None
        for _ in range(timeout):
            await asyncio.sleep(1)
            if self.state.get(0x02) == c:
                print(f"   confirmed: setpoint = {c}")
                return True
        print(f"   NOT confirmed: setpoint still {self.state.get(0x02)}")
        return False

    async def wait_for_state(self, dpid=0x02, timeout=20):
        for _ in range(timeout):
            if dpid in self.state:
                return self.state[dpid]
            await asyncio.sleep(1)
        return None

    async def close(self):
        if self.client and self.client.is_connected:
            await self.client.disconnect()


async def main():
    ac = Helium()
    await ac.connect()
    try:
        # the passkey packet also provokes a full datapoint dump
        await asyncio.sleep(2)
        await ac.send(p_passkey(PASSKEY))
        await ac.wait_for_state(0x02)

        if len(sys.argv) > 1:
            await ac.set_temp(int(sys.argv[1]))
        else:
            await asyncio.sleep(4)

        print("\nstate:", {DP_NAMES.get(k, hex(k)): v for k, v in sorted(ac.state.items())})
    finally:
        await ac.close()

if __name__ == "__main__":
    asyncio.run(main())
