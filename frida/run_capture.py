#!/usr/bin/env python3
"""Spawn the Helium app under Frida (gated), install hooks BEFORE it runs, resume."""
import frida, sys, time

def on_message(m, d):
    if m["type"] == "send":
        print(m["payload"], flush=True)
    else:
        print("[frida-error]", m.get("stack", m), flush=True)

dev = frida.get_usb_device(timeout=10)
pid = dev.spawn(["com.helium.mobileapp"])   # start suspended
session = dev.attach(pid)
script = session.create_script(open("capture.js").read())
script.on("message", on_message)
script.load()
dev.resume(pid)
print(f"[runner] spawned pid={pid}, hooks installed, resumed", flush=True)
sys.stdin.read()
