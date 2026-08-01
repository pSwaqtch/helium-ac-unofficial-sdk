def check(hexstr):
    b = bytes.fromhex(hexstr)
    body, cs = b[:-1], b[-1]
    calc = sum(body) & 0xFF
    return cs, calc, cs == calc

for f in ["55aa030700081c020004000002cd02", "55aa030700081c020004000002e419"]:
    cs, calc, ok = check(f)
    val = int(f[-10:-2], 16)
    print(f"{f}  value={val:5d}  cs=0x{cs:02x} calc=0x{calc:02x}  {'OK' if ok else 'MISMATCH'}")
