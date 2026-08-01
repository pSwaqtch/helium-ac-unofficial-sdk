#!/usr/bin/env python3
"""Attach to the Helium gadget, load hook.js, and log messages until killed."""
import frida, sys, time

def on_message(msg, data):
    if msg["type"] == "send":
        print(msg["payload"], flush=True)
    elif msg["type"] == "error":
        print("[frida-error]", msg.get("stack", msg), flush=True)

def main():
    dev = frida.get_usb_device(timeout=10)
    # attach by name; gadget exposes the app as "Helium Air"
    session = dev.attach("Helium Air")
    with open("hook.js") as f:
        src = f.read()
    # route console.log through send() so it reaches us
    src = "var __log=console.log; console.log=function(){ send(Array.prototype.slice.call(arguments).join(' ')); };\n" + src
    script = session.create_script(src)
    script.on("message", on_message)
    script.load()
    print("[capture] attached and loaded; waiting for events (Ctrl-C to stop)", flush=True)
    sys.stdin.read()

if __name__ == "__main__":
    main()
