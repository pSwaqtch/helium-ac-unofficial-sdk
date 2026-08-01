#!/usr/bin/env python3
"""
Parse an Android btsnoop_hci.log and decode ATT traffic as Helium packets.

btsnoop format: 16-byte file header, then per-record:
    u32 original_length, u32 included_length, u32 flags, u32 drops, u64 timestamp
followed by `included_length` bytes of HCI data.

flags bit0: 0 = host->controller (sent), 1 = controller->host (received)
We care about ACL data (HCI packet type 0x02) carrying L2CAP CID 0x0004 (ATT).
"""
import struct, sys, collections

CMD_NAMES = {600: "BLE_PASSKEY", 500: "STATUS_DATA", 1003: "AC_CTRL",
             100: "FIRMWARE_UPDATE", 101: "VFS_UPDATE", 109: "FACTORY_RESET",
             103: "SAVE_DEVICE_NAME", 700: "WIFI", 105: "USER_ID"}
AC_SUB = {0: "POWER", 1: "FAN", 2: "TEMP", 3: "MODE", 4: "VSWING",
          5: "TURBO", 6: "SLEEP"}
OPS = {0x12: "WriteReq", 0x52: "WriteCmd", 0x1b: "Notify", 0x1d: "Indicate",
       0x0a: "ReadReq", 0x0b: "ReadRsp", 0x13: "WriteRsp", 0x52: "WriteCmd"}


def records(path):
    with open(path, "rb") as f:
        if f.read(8) != b"btsnoop\x00":
            raise SystemExit("not a btsnoop file")
        f.read(8)  # version + datalink
        while True:
            hdr = f.read(24)
            if len(hdr) < 24:
                return
            olen, ilen, flags, drops, ts = struct.unpack(">IIIIq", hdr)
            data = f.read(ilen)
            if len(data) < ilen:
                return
            yield ts, flags, data


def att_stream(path):
    """Yield (ts, is_rx, handle_or_none, att_bytes), reassembling L2CAP."""
    pending = {}  # acl_handle -> (need, buf)
    for ts, flags, d in records(path):
        if not d:
            continue
        ptype, body = d[0], d[1:]
        if ptype != 0x02 or len(body) < 4:
            continue
        h, blen = struct.unpack("<HH", body[:4])
        acl_handle = h & 0x0FFF
        pb = (h >> 12) & 0x3
        payload = body[4:4 + blen]
        is_rx = bool(flags & 1)

        if pb == 0x01:  # continuation
            if acl_handle in pending:
                need, buf, rx0 = pending[acl_handle]
                buf += payload
                if len(buf) >= need:
                    cid = struct.unpack("<H", buf[2:4])[0]
                    if cid == 0x0004:
                        yield ts, rx0, buf[4:4 + need - 0]
                    del pending[acl_handle]
                else:
                    pending[acl_handle] = (need, buf, rx0)
            continue

        # first fragment
        if len(payload) < 4:
            continue
        l2len, cid = struct.unpack("<HH", payload[:4])
        if len(payload) - 4 < l2len:
            pending[acl_handle] = (l2len, payload, is_rx)
            continue
        if cid == 0x0004:
            yield ts, is_rx, payload[4:4 + l2len]


def decode_helium(b):
    if len(b) < 25 or b[0] != 0xFF:
        return None
    cmd = int.from_bytes(b[1:3], "big")
    out = {
        "cmd": cmd, "cmd_name": CMD_NAMES.get(cmd, "?"),
        "len": int.from_bytes(b[3:5], "big"),
        "seq": int.from_bytes(b[5:7], "big"),
        "checksum": int.from_bytes(b[7:11], "big"),
        "total_level": b[11],
        "level": b[12:17].hex(),
        "totalSize": int.from_bytes(b[17:21], "big"),
        "params": int.from_bytes(b[21:25], "big"),
        "payload": b[25:],
    }
    return out


def main(path):
    t0 = None
    counts = collections.Counter()
    for ts, is_rx, att in att_stream(path):
        if not att:
            continue
        op = att[0]
        counts[OPS.get(op, hex(op))] += 1
        if op not in (0x12, 0x52, 0x1b, 0x1d):
            continue
        if len(att) < 3:
            continue
        handle = int.from_bytes(att[1:3], "little")
        val = att[3:]
        if t0 is None:
            t0 = ts
        rel = (ts - t0) / 1e6
        arrow = "<-- DEV" if is_rx else "APP -->"
        print(f"[{rel:8.3f}s] {arrow} {OPS.get(op,hex(op)):9s} h=0x{handle:04x} ({len(val)} B)")
        print(f"            raw = {val.hex(' ')}")
        d = decode_helium(val)
        if d:
            print(f"            >>> cmd={d['cmd']}({d['cmd_name']}) len={d['len']} "
                  f"seq={d['seq']} cks=0x{d['checksum']:08x} tot_lvl={d['total_level']} "
                  f"level={d['level']} totalSize={d['totalSize']} params={d['params']}")
            pl = d["payload"]
            if d["cmd"] == 1003 and len(pl) >= 5:
                print(f"            >>> AC_CTRL sub={pl[0]}({AC_SUB.get(pl[0],'?')}) "
                      f"data={pl[5:].hex(' ')}")
            else:
                print(f"            >>> payload={pl.hex(' ')} ascii={pl.decode('ascii','replace')!r}")
        else:
            try:
                s = val.decode("ascii")
                if s.isprintable() or "\n" in s:
                    print(f"            ascii = {s[:100]!r}")
            except Exception:
                pass
        print()
    print("ATT opcode counts:", dict(counts))


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "FS/data/misc/bluetooth/logs/btsnoop_hci.log")
