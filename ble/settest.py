import asyncio, sys
from helium import Helium, p_temp, p_passkey

async def main():
    target = int(sys.argv[1])
    ac = Helium(); ac.verbose = False
    await ac.connect()
    try:
        # wait for a REAL baseline: DP2 must actually be present before we judge
        for _ in range(20):
            await asyncio.sleep(1)
            if 0x02 in ac.state:
                break
        before = ac.state.get(0x02)
        if before is None:
            print("never saw a setpoint report; aborting")
            return
        if before == target:
            print(f"setpoint already {target} — pick a different target")
            return

        print(f"\n=== baseline setpoint = {before}, requesting {target} ===")
        await ac.send(p_passkey("1111"))
        await asyncio.sleep(2)
        await ac.send(p_temp(target))

        for _ in range(15):
            await asyncio.sleep(1)
            now = ac.state.get(0x02)
            if now != before:
                verdict = "as requested" if now == target else f"but expected {target}"
                print(f"\n*** setpoint CHANGED {before} -> {now} ({verdict}) ***")
                return
        print(f"\n--- NO CHANGE: setpoint still {ac.state.get(0x02)} after 15s ---")
    finally:
        await ac.close()

asyncio.run(main())
