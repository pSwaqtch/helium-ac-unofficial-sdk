import asyncio
from bleak import BleakScanner

async def main():
    devs = await BleakScanner.discover(timeout=8.0, return_adv=True)
    for addr, (d, adv) in devs.items():
        name = d.name or adv.local_name or ""
        if "HELM" in (name or "").upper() or "7f93" in addr.lower():
            print("*** MATCH ***")
        print(f"{addr}  rssi={adv.rssi}  name={name!r}")
        if adv.service_uuids: print("     svc:", adv.service_uuids)
        if adv.manufacturer_data: print("     mfg:", {k: v.hex() for k,v in adv.manufacturer_data.items()})
asyncio.run(main())
