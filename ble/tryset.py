import asyncio, datetime, sys, re
from bleak import BleakClient
ADDR="93E01E83-F89E-9B1A-75C6-C28E886BCFC4"
B002="0000b002-0000-1000-8000-00805f9b34fb"
B003="0000b003-0000-1000-8000-00805f9b34fb"

def frame(dpid, val, ty=2, dlen=4, cmd=0x06):
    body = bytes([0x55,0xaa,0x03,cmd]) 
    pl = bytes([dpid,ty]) + dlen.to_bytes(2,'big') + val.to_bytes(dlen,'big')
    body += len(pl).to_bytes(2,'big') + pl
    return body + bytes([sum(body)&0xFF])

TEMP = int(sys.argv[1]) if len(sys.argv)>1 else 24
f = frame(0x02, TEMP)
hexs = f.hex()
print("target temp:", TEMP)
print("raw frame  :", f.hex(' '))

CANDIDATES = [
    ("raw bytes",            f),
    ("hex ascii",            hexs.encode()),
    ("hex ascii + NUL",      hexs.encode()+b"\x00"),
    ("Cmd:1:<hex>",          f"Cmd:1:{hexs}".encode()+b"\x00"),
    ("Set:1:<hex>",          f"Set:1:{hexs}".encode()+b"\x00"),
    ("Ctrl:1:<hex>",         f"Ctrl:1:{hexs}".encode()+b"\x00"),
    ("Poll:1:<hex>",         f"Poll:1:{hexs}".encode()+b"\x00"),
]

events=[]
def h(_, data):
    raw=bytes(data).rstrip(b"\x00").decode("ascii","replace")
    m=re.match(r"Poll:\d+:([0-9a-fA-F]+)",raw)
    tag=""
    if m:
        b=bytes.fromhex(m.group(1))
        if len(b)>=10 and b[6]==0x02:
            tag=f"  <<< DP2 = {int.from_bytes(b[10:14],'big')}"
    if tag or "Diag" in raw:
        t=datetime.datetime.now().strftime("%H:%M:%S")
        events.append(f"[{t}] {raw[:70]}{tag}")

async def main():
    async with BleakClient(ADDR, timeout=25.0) as c:
        await c.start_notify(B003,h)
        await asyncio.sleep(2)
        for name,payload in CANDIDATES:
            events.clear()
            print(f"\n--- trying: {name}  ({len(payload)} B) ---")
            for wr in (False,True):
                try:
                    await c.write_gatt_char(B002,payload,response=wr)
                    print(f"    write(response={wr}) accepted")
                except Exception as e:
                    print(f"    write(response={wr}) FAILED: {type(e).__name__}: {e}")
                await asyncio.sleep(2.5)
            for e in events[-6:]: print("   ",e)
asyncio.run(main())
