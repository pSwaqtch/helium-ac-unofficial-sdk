import asyncio, re
from bleak import BleakScanner, BleakClient
B002="0000b002-0000-1000-8000-00805f9b34fb"
B003="0000b003-0000-1000-8000-00805f9b34fb"
seen=[]
def cb(_,data):
    raw=bytes(data).rstrip(b"\x00").decode("ascii","replace")
    seen.append(raw)
async def main():
    dev=None
    def f(d,adv):
        nonlocal dev
        n=d.name or adv.local_name or ""
        if "7f93" in n.lower() and dev is None: dev=d
    s=BleakScanner(f); await s.start()
    for _ in range(25):
        await asyncio.sleep(1)
        if dev: break
    await s.stop()
    if dev is None:
        raise SystemExit("AC not advertising (another central may hold it)")
    async with BleakClient(dev,timeout=25.0) as c:
        await c.start_notify(B003,cb)
        await asyncio.sleep(4)
        print(f"--- {len(seen)} notifications before write ---")
        for x in seen[-5:]: print("   ",x[:80])
        seen.clear()
        print("\n>>> writing passkey '1111' as ASCII")
        await c.write_gatt_char(B002,b"1111",response=False)
        await asyncio.sleep(6)
        print(f"--- {len(seen)} notifications after ---")
        for x in seen: print("   ",x[:100])
asyncio.run(main())
