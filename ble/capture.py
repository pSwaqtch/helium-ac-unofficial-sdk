import asyncio, datetime, sys, re
from bleak import BleakClient
ADDR="93E01E83-F89E-9B1A-75C6-C28E886BCFC4"
B003="0000b003-0000-1000-8000-00805f9b34fb"
B004="0000b004-0000-1000-8000-00805f9b34fb"
DUR=int(sys.argv[1]) if len(sys.argv)>1 else 90
LOG=open(f"captures/cap_{datetime.datetime.now():%H%M%S}.log","w")

TYPES={0:"raw",1:"bool",2:"int",3:"str",4:"enum",5:"bitmap"}
seen={}

def parse_tuya(h):
    try: b=bytes.fromhex(h)
    except: return None
    if len(b)<7 or b[0]!=0x55 or b[1]!=0xaa: return None
    ver,cmd=b[2],b[3]; ln=int.from_bytes(b[4:6],'big')
    pl=b[6:6+ln]; out=[f"ver={ver} cmd=0x{cmd:02x} len={ln}"]
    i=0
    while i+4<=len(pl):
        dpid,ty=pl[i],pl[i+1]; dlen=int.from_bytes(pl[i+2:i+4],'big')
        val=pl[i+4:i+4+dlen]
        if ty==2 or ty==1 or ty==4: v=int.from_bytes(val,'big')
        else: v=val.hex()
        out.append(f"DP{dpid}(0x{dpid:02x}) {TYPES.get(ty,ty)} = {v}")
        prev=seen.get(dpid)
        if prev is not None and prev!=v: out.append(f"  *** DP{dpid} CHANGED {prev} -> {v} ***")
        seen[dpid]=v
        i+=4+dlen
    return " | ".join(out)

def mk(tag):
    def h(_, data):
        t=datetime.datetime.now().strftime("%H:%M:%S.%f")[:-3]
        raw=bytes(data).rstrip(b"\x00").decode("ascii","replace")
        line=f"[{t}] {tag} {raw}"
        m=re.match(r"Poll:\d+:([0-9a-fA-F]+)",raw)
        if m:
            d=parse_tuya(m.group(1))
            if d: line+=f"\n         >> {d}"
        print(line); LOG.write(line+"\n"); LOG.flush()
    return h

async def main():
    async with BleakClient(ADDR, timeout=25.0) as c:
        await c.start_notify(B003, mk("B003"))
        try: await c.start_notify(B004, mk("B004"))
        except: pass
        print(f"=== CAPTURING {DUR}s -> {LOG.name} ===")
        await asyncio.sleep(DUR)
asyncio.run(main())
