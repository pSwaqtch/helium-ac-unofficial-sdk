import asyncio
from bleak import BleakClient

ADDR = "93E01E83-F89E-9B1A-75C6-C28E886BCFC4"

async def main():
    async with BleakClient(ADDR, timeout=25.0) as c:
        print("connected:", c.is_connected, " mtu:", c.mtu_size)
        for s in c.services:
            print(f"\nSERVICE {s.uuid}  ({s.description})")
            for ch in s.characteristics:
                props = ",".join(ch.properties)
                val = ""
                if "read" in ch.properties:
                    try:
                        b = await c.read_gatt_char(ch)
                        val = f"  = {b.hex(' ')}  |{b.decode('ascii','replace')}|"
                    except Exception as e:
                        val = f"  <read err {e}>"
                print(f"  CHAR {ch.uuid}  h={ch.handle}  [{props}]{val}")
                for d in ch.descriptors:
                    try:
                        db = await c.read_gatt_descriptor(d.handle)
                        print(f"      DESC {d.uuid} = {db.hex(' ')}")
                    except Exception as e:
                        print(f"      DESC {d.uuid} <err>")
asyncio.run(main())
