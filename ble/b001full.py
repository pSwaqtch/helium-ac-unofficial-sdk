import asyncio, re
from bleak import BleakClient
ADDR="93E01E83-F89E-9B1A-75C6-C28E886BCFC4"
B001="0000b001-0000-1000-8000-00805f9b34fb"
async def main():
    async with BleakClient(ADDR,timeout=25.0) as c:
        b=await c.read_gatt_char(B001)
        print(f"len={len(b)}")
        print(b.hex(' '))
        print()
        # pull printable runs
        for m in re.finditer(rb"[ -~]{4,}", bytes(b)):
            print(f"  @{m.start():3d}  {m.group().decode()}")
asyncio.run(main())
