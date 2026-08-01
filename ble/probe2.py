import asyncio, datetime, re
from bleak import BleakClient
ADDR="93E01E83-F89E-9B1A-75C6-C28E886BCFC4"
B002="0000b002-0000-1000-8000-00805f9b34fb"
B003="0000b003-0000-1000-8000-00805f9b34fb"
B004="0000b004-0000-1000-8000-00805f9b34fb"

def tuya(cmd, pl=b""):
    body = bytes([0x55,0xaa,0x03,cmd]) + len(pl).to_bytes(2,'big') + pl
    return body + bytes([sum(body)&0xFF])

dp2 = bytes([0x02,0x02])+ (4).to_bytes(2,'big') + (24).to_bytes(4,'big')

# vary the tuya command byte
TRIALS=[]
for cmd in (0x00,0x01,0x02,0x03,0x04,0x05,0x06,0x07,0x08,0x09,0x0a,0x0d,0x0e,0x10,0x22,0x34):
    TRIALS.append((f"tuya cmd=0x{cmd:02x} raw", tuya(cmd, dp2)))

baseline=set()
events=[]
def h(tag):
    def f(_,data):
        raw=bytes(data).rstrip(b"\x00").decode("ascii","replace")
        # ignore known-noise lines
        if re.match(r"Diag:\d+:(Publishing to|->100149c4|\s*)$", raw): return
        if re.match(r"Poll:\d+:55aa030700081c02", raw): return  # power only
        events.append(f"{tag} {raw[:90]}")
    return f

async def main():
    async with BleakClient(ADDR, timeout=25.0) as c:
        await c.start_notify(B003,h("B003"))
        try: await c.start_notify(B004,h("B004"))
        except: pass
        await asyncio.sleep(2)
        for name,payload in TRIALS:
            events.clear()
            try: await c.write_gatt_char(B002,payload,response=False)
            except Exception as e:
                print(f"{name:26s} WRITE-ERR {e}"); continue
            await asyncio.sleep(1.8)
            if events:
                print(f"{name:26s} >>> REACTION:")
                for e in events[:4]: print("      ",e)
            else:
                print(f"{name:26s} (silent)")
asyncio.run(main())
