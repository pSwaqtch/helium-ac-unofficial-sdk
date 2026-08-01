import asyncio
from bleak import BleakScanner

async def main():
    found = {}
    def cb(d, adv):
        n = d.name or adv.local_name or ""
        if "7f93" in n.lower():
            found[d.address] = (n, adv.rssi)
    s = BleakScanner(cb)
    await s.start()
    for _ in range(30):
        await asyncio.sleep(1)
        if found: break
    await s.stop()
    for a,(n,r) in found.items():
        print(f"ADDR={a}  name={n}  rssi={r}")
    if not found: print("not found")
asyncio.run(main())
