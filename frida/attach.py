import frida, sys, time
def om(m,d):
    if m["type"]=="send": print(m["payload"],flush=True)
    else: print("[err]",m.get("stack",m),flush=True)
dev=frida.get_usb_device(timeout=10)
try:
    s=dev.attach("Helium Air")
    print("[attach] OK",flush=True)
    sc=s.create_script(open("capture.js").read())
    sc.on("message",om); sc.load()
    print("[attach] script loaded",flush=True)
    time.sleep(3600)
except Exception as e:
    print("[attach] FAILED:",e,flush=True)
