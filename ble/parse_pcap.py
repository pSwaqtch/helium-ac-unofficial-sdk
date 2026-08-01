#!/usr/bin/env python3
"""
Extract ATT writes from an nRF Sniffer pcap and decode them as Helium packets.

The sniffer writes DLT_NORDIC_BLE (272) records: each packet payload is a
Nordic header, then the BLE link-layer PDU. We walk the LL payload to the L2CAP
frame, keep CID 0x0004 (ATT), and decode Write Request (0x12) /
Write Command (0x52).
"""
import struct, sys, collections

def records(path):
    with open(path, "rb") as f:
        gh = f.read(24)
        if len(gh) < 24:
            return
        magic, = struct.unpack("<I", gh[:4])
        endian = "<" if magic in (0xa1b2c3d4, 0xa1b23c4d) else ">"
        while True:
            hdr = f.read(16)
            if len(hdr) < 16:
                return
            ts, tus, caplen, origlen = struct.unpack(endian + "IIII", hdr)
            data = f.read(caplen)
            if len(data) < caplen:
                return
            yield ts + tus / 1e6, data


def att_pdus(path):
    for ts, d in records(path):
        # Nordic header: board id (1) + header len (1) ... then BLE packet
        if len(d) < 2:
            continue
        hlen = d[1]
        ble = d[hlen:]
        # access address (4) + LL header (2)
        if len(ble) < 6:
            continue
        llid = ble[4] & 0x03
        pdulen = ble[5]
        payload = ble[6:6 + pdulen]
        # L2CAP start frame only (llid 2); continuation frames not reassembled
        if llid != 2 or len(payload) < 4:
            continue
        l2len, cid = struct.unpack("<HH", payload[:4])
        if cid != 0x0004:
            continue
        att = payload[4:4 + l2len]
        if att:
            yield ts, att


OPS = {0x12: "WriteReq", 0x52: "WriteCmd", 0x1b: "Notify", 0x1d: "Indicate",
       0x0a: "ReadReq", 0x0b: "ReadRsp", 0x13: "WriteRsp"}

CMD_NAMES = {600: "BLE_PASSKEY", 500: "STATUS_DATA", 1003: "AC_CTRL",
             100: "FIRMWARE_UPDATE", 101: "VFS_UPDATE", 109: "FACTORY_RESET",
             103: "SAVE_DEVICE_NAME", 700: "WIFI", 105: "USER_ID"}

AC_SUB = {0: "POWER", 1: "FAN", 2: "TEMP", 3: "MODE", 4: "VSWING",
          5: "TURBO", 6: "SLEEP"}


def decode_helium(b):
    """Decode a Helium 25-byte-header packet, if it looks like one."""
    if len(b) < 25 or b[0] != 0xFF:
        return None
    cmd = int.from_bytes(b[1:3], "big")
    ln = int.from_bytes(b[3:5], "big")
    seq = int.from_bytes(b[5:7], "big")
    cks = int.from_bytes(b[7:11], "big")
    tot_lvl = b[11]
    level = b[12:17]
    totsz = int.from_bytes(b[17:21], "big")
    params = int.from_bytes(b[21:25], "big")
    pl = b[25:]
    s = (f"cmd={cmd}({CMD_NAMES.get(cmd,'?')}) len={ln} seq={seq} "
         f"cks=0x{cks:08x} tot_lvl={tot_lvl} level={level.hex()} "
         f"totalSize={totsz} params={params}")
    if cmd == 1003 and len(pl) >= 5:
        s += f"\n            AC_CTRL sub={pl[0]}({AC_SUB.get(pl[0],'?')}) data={pl[5:].hex(' ')}"
    else:
        s += f"\n            payload={pl.hex(' ')}  ascii={pl.decode('ascii','replace')!r}"
    return s


def main(path):
    n = 0
    counts = collections.Counter()
    t0 = None
    for ts, att in att_pdus(path):
        op = att[0]
        counts[OPS.get(op, hex(op))] += 1
        if op not in (0x12, 0x52):
            continue
        if len(att) < 3:
            continue
        handle = int.from_bytes(att[1:3], "little")
        val = att[3:]
        if t0 is None:
            t0 = ts
        n += 1
        print(f"[{ts-t0:7.3f}s] {OPS[op]} handle=0x{handle:04x} ({len(val)} B)")
        print(f"            raw={val.hex(' ')}")
        dec = decode_helium(val)
        if dec:
            print(f"            >>> {dec}")
        print()
    print(f"--- {n} writes; ATT opcode counts: {dict(counts)} ---")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "captures/session.pcap")
