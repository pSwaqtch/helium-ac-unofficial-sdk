import asyncio, sys
from helium import Helium, p_temp, p_passkey

async def main():
    target = int(sys.argv[1])
    ac = Helium(); ac.verbose = False
    await ac.connect()
    try:
        await asyncio.sleep(2)
        print("sending passkey (also provokes full state dump)...")
        await ac.send(p_passkey("1111"))
        for _ in range(20):
            await asyncio.sleep(1)
            if 0x02 in ac.state: break
        before = ac.state.get(0x02)
        if before is None:
            print("no setpoint seen. state:", sorted(hex(k) for k in ac.state)); return
        print(f"\n=== baseline setpoint = {before}, requesting {target} ===")
        await ac.send(p_temp(target))
        for _ in range(18):
            await asyncio.sleep(1)
            now = ac.state.get(0x02)
            if now != before:
                v = "as requested" if now==target else f"but expected {target}"
                print(f"\n*** setpoint CHANGED {before} -> {now} ({v}) ***"); return
        print(f"\n--- NO CHANGE: still {ac.state.get(0x02)} ---")
    finally:
        await ac.close()
asyncio.run(main())
