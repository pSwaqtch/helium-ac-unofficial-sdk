import asyncio, datetime, re
from bleak import BleakClient
ADDR="93E01E83-F89E-9B1A-75C6-C28E886BCFC4"
B003="0000b003-0000-1000-8000-00805f9b34fb"
n=0; kinds={}
def h(_,data):
    global n
    raw=bytes(data).rstrip(b"\x00").decode("ascii","replace")
    n+=1
    k=re.sub(r"\d+","N",raw)[:55]
    kinds[k]=kinds.get(k,0)+1
async def main():
    async with BleakClient(ADDR,timeout=25.0) as c:
        await c.start_notify(B003,h)
        print("30s passive baseline, NO writes at all...")
        await asyncio.sleep(30)
    print(f"total notifications: {n}  ({n/30:.1f}/sec)")
    for k,v in sorted(kinds.items(),key=lambda x:-x[1]): print(f"  {v:4d}x  {k}")
asyncio.run(main())
