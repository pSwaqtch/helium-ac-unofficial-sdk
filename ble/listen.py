import asyncio, datetime
from bleak import BleakClient
ADDR="93E01E83-F89E-9B1A-75C6-C28E886BCFC4"
B003="0000b003-0000-1000-8000-00805f9b34fb"
B004="0000b004-0000-1000-8000-00805f9b34fb"
def mk(tag):
    def h(_, data):
        t=datetime.datetime.now().strftime("%H:%M:%S.%f")[:-3]
        print(f"[{t}] {tag} ({len(data)}) {data.hex(' ')}")
        print(f"          ascii |{bytes(data).decode('ascii','replace')}|")
    return h
async def main():
    async with BleakClient(ADDR, timeout=25.0) as c:
        await c.start_notify(B003, mk("B003"))
        try: await c.start_notify(B004, mk("B004"))
        except Exception as e: print("B004 sub failed:", e)
        print("subscribed, listening 25s (idle baseline)...")
        await asyncio.sleep(25)
asyncio.run(main())
