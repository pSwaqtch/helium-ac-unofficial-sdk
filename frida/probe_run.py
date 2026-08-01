import frida,sys
def om(m,d):
    if m["type"]=="send": print(m["payload"],flush=True)
    else: print("[err]",m,flush=True)
s=frida.get_usb_device(timeout=10).attach("Helium Air")
sc=s.create_script(open("probe.js").read())
sc.on("message",om); sc.load()
import time; time.sleep(4)
