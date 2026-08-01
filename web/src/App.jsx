import React, { useEffect, useState } from "react";

const MIN_C = 16;
const MAX_C = 30;
const FANS = ["auto", "low", "medium", "high"];
const MODES = ["cool", "heat"];

async function api(path, opts) {
  const r = await fetch(path, opts);
  const body = await r.json().catch(() => ({ error: "bad JSON from server" }));
  if (!r.ok) throw new Error(body.error || `HTTP ${r.status}`);
  return body;
}

function Section({ title, children, muted }) {
  return (
    <section
      className={`rounded-xl border border-slate-700 bg-slate-800/50 p-4 ${
        muted ? "opacity-70" : ""
      }`}
    >
      <h2 className="mb-3 text-xs font-semibold uppercase tracking-wider text-slate-400">
        {title}
      </h2>
      {children}
    </section>
  );
}

function Btn({ active, className = "", ...props }) {
  return (
    <button
      className={`rounded-lg px-3 py-2 text-sm font-medium transition
        disabled:cursor-not-allowed disabled:opacity-40
        ${
          active
            ? "bg-sky-500 text-white"
            : "bg-slate-700 text-slate-200 hover:bg-slate-600"
        } ${className}`}
      {...props}
    />
  );
}

/** on/off pair — the AC has no "read back" for most of these, so neither is preselected */
function Toggle({ label, onSend, disabled }) {
  return (
    <div className="flex items-center justify-between gap-3">
      <span className="text-sm text-slate-300">{label}</span>
      <div className="flex gap-2">
        <Btn disabled={disabled} onClick={() => onSend(true)}>
          On
        </Btn>
        <Btn disabled={disabled} onClick={() => onSend(false)}>
          Off
        </Btn>
      </div>
    </div>
  );
}

export default function App() {
  const [transport, setTransport] = useState(
    () => localStorage.getItem("transport") || "cloud"
  );
  const [busy, setBusy] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [state, setState] = useState(null);
  const [readAt, setReadAt] = useState(null);
  const [log, setLog] = useState([]);
  const [error, setError] = useState(null);
  const [bleConnected, setBleConnected] = useState(false);
  const [setpoint, setSetpoint] = useState(24);
  const [timerMin, setTimerMin] = useState(30);
  const [convertible, setConvertible] = useState(0);

  useEffect(() => localStorage.setItem("transport", transport), [transport]);

  useEffect(() => {
    api("/api/ble/status")
      .then((s) => setBleConnected(s.connected))
      .catch(() => {});
  }, []);

  // pull current state on load and whenever the transport changes, so the panel
  // always opens showing where the AC actually is
  useEffect(() => {
    readState({ quiet: true });
  }, [transport]);

  function note(entry) {
    setLog((l) => [{ at: new Date().toLocaleTimeString(), ...entry }, ...l].slice(0, 12));
  }

  async function send(field, value) {
    setBusy(true);
    setError(null);
    try {
      const res = await api(`/api/ac/command?transport=${transport}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ [field]: value }),
      });
      note({ cmd: `${field}=${JSON.stringify(value)}`, transport: res.transport, hex: res.payload });
      // let the unit settle, then refresh so the readout reflects what we just did
      setTimeout(() => readState({ quiet: true }), 1500);
    } catch (e) {
      setError(e.message);
      note({ cmd: `${field}=${JSON.stringify(value)}`, transport, error: e.message });
    } finally {
      setBusy(false);
    }
  }

  async function readState({ quiet = false } = {}) {
    setRefreshing(true);
    if (!quiet) setError(null);
    try {
      const res = await api(`/api/ac/state?transport=${transport}`);
      // the cloud dump is intermittent (PROTOCOL §7j) — an empty read means the
      // device didn't answer, not that everything is unknown. Keep what we had.
      if (Object.keys(res.state).length === 0) {
        if (!quiet) setError("No state returned — device didn't answer, try again.");
        return;
      }
      setState(res.state);
      setReadAt(new Date().toLocaleTimeString());
      if (res.state.setpoint_C) setSetpoint(res.state.setpoint_C);
      if (!quiet) note({ cmd: "read state", transport: res.transport });
    } catch (e) {
      // a background refresh failing shouldn't stomp on the UI with an error
      if (!quiet) setError(e.message);
      // a BLE read failing usually means the link dropped (phone app grabbed the
      // AC, or out of range) — resync the flag so the UI stops claiming connected
      if (transport === "ble") {
        api("/api/ble/status").then((s) => setBleConnected(s.connected)).catch(() => {});
      }
    } finally {
      setRefreshing(false);
    }
  }

  async function ble(action) {
    setBusy(true);
    setError(null);
    try {
      const res = await api(`/api/ble/${action}`, { method: "POST" });
      setBleConnected(res.connected);
      note({ cmd: `ble ${action}`, transport: "ble" });
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }

  function bumpTemp(delta) {
    const next = Math.min(MAX_C, Math.max(MIN_C, setpoint + delta));
    setSetpoint(next);
    send("temperature", next);
  }

  return (
    <div className="min-h-screen bg-slate-900 px-4 py-8 text-slate-100">
      <div className="mx-auto flex max-w-3xl flex-col gap-4">
        <header className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h1 className="text-2xl font-semibold">Helium AC</h1>
            <p className="text-sm text-slate-400">Dual-transport control panel</p>
          </div>
          <div className="flex items-center gap-2">
            <div className="flex rounded-lg bg-slate-800 p-1">
              {["ble", "cloud"].map((t) => (
                <button
                  key={t}
                  onClick={() => setTransport(t)}
                  className={`rounded-md px-4 py-1.5 text-sm font-medium uppercase transition ${
                    transport === t ? "bg-sky-500 text-white" : "text-slate-400 hover:text-slate-200"
                  }`}
                >
                  {t}
                </button>
              ))}
            </div>
          </div>
        </header>

        <div className="rounded-xl border border-slate-700 bg-slate-800/50 p-4">
          <div className="mb-3 flex items-center justify-between">
            <span className="text-xs font-semibold uppercase tracking-wider text-slate-400">
              Current state
            </span>
            <span className="text-xs text-slate-500">
              {refreshing ? "refreshing…" : readAt ? `read ${readAt}` : "not read yet"}
            </span>
          </div>
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-5">
            {[
              ["Power", state?.power === undefined ? undefined : state.power ? "on" : "off", ""],
              ["Setpoint", state?.setpoint_C, "°"],
              ["Room", state?.room_temp_C, "°"],
              ["Draw", state?.power_W, "W"],
              ["Fan", state?.fan === undefined ? undefined : FANS[state.fan] ?? state.fan, ""],
            ].map(([label, value, unit]) => (
              <div key={label}>
                <div className="text-xs text-slate-500">{label}</div>
                <div className="text-xl font-semibold tabular-nums text-slate-100">
                  {value === undefined ? "—" : `${value}${unit}`}
                </div>
              </div>
            ))}
          </div>
        </div>

        {transport === "ble" && (
          <div className="flex items-center justify-between rounded-xl border border-slate-700 bg-slate-800/50 px-4 py-3">
            <span className="text-sm text-slate-300">
              BLE link:{" "}
              <span className={bleConnected ? "text-emerald-400" : "text-slate-500"}>
                {bleConnected ? "connected" : "not connected"}
              </span>
              <span className="ml-2 text-xs text-slate-500">
                (needs the phone app disconnected from the AC)
              </span>
            </span>
            <div className="flex gap-2">
              <Btn disabled={busy} onClick={() => ble("connect")}>Connect</Btn>
              <Btn disabled={busy} onClick={() => ble("disconnect")}>Disconnect</Btn>
            </div>
          </div>
        )}

        {error && (
          <div className="rounded-lg border border-red-800 bg-red-950/60 px-4 py-2 text-sm text-red-300">
            {error}
          </div>
        )}

        <Section title="Power & temperature">
          <div className="flex flex-wrap items-center gap-6">
            <div className="flex gap-2">
              <Btn disabled={busy} onClick={() => send("power", true)}>Power on</Btn>
              <Btn disabled={busy} onClick={() => send("power", false)}>Power off</Btn>
            </div>
            <div className="flex items-center gap-3">
              <Btn disabled={busy || setpoint <= MIN_C} onClick={() => bumpTemp(-1)} className="w-12 text-lg">
                −
              </Btn>
              <div className="w-20 text-center">
                <div className="text-3xl font-semibold tabular-nums">{setpoint}°</div>
                <div className="text-xs text-slate-500">setpoint</div>
              </div>
              <Btn disabled={busy || setpoint >= MAX_C} onClick={() => bumpTemp(1)} className="w-12 text-lg">
                +
              </Btn>
            </div>
          </div>
        </Section>

        <div className="grid gap-4 sm:grid-cols-2">
          <Section title="Mode">
            <div className="flex gap-2">
              {MODES.map((m) => (
                <Btn
                  key={m}
                  disabled={busy}
                  active={state?.mode !== undefined && m === (state.mode === 1 ? "cool" : "heat")}
                  onClick={() => send("mode", m)}
                  className="capitalize"
                >
                  {m}
                </Btn>
              ))}
            </div>
          </Section>

          <Section title="Fan speed">
            <div className="flex flex-wrap gap-2">
              {FANS.map((f, i) => (
                <Btn key={f} disabled={busy} active={state?.fan === i} onClick={() => send("fan", f)} className="capitalize">
                  {f}
                </Btn>
              ))}
            </div>
          </Section>
        </div>

        <Section title="Airflow & comfort">
          <div className="grid gap-3 sm:grid-cols-2">
            <Toggle label="Vertical swing" disabled={busy} onSend={(v) => send("verticalSwing", v)} />
            <Toggle label="Horizontal swing" disabled={busy} onSend={(v) => send("horizontalSwing", v)} />
            <Toggle label="Turbo" disabled={busy} onSend={(v) => send("turbo", v)} />
            <Toggle label="Sleep" disabled={busy} onSend={(v) => send("sleep", v)} />
            <Toggle label="Display" disabled={busy} onSend={(v) => send("display", v)} />
            <Toggle label="Silent" disabled={busy} onSend={(v) => send("silent", v)} />
          </div>
        </Section>

        <Section title="Live state">
          <div className="mb-3">
            <Btn disabled={busy || refreshing} onClick={() => readState()}>
              {refreshing ? "Reading…" : "Read state"}
            </Btn>
          </div>
          {state ? (
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
              {[
                ["Setpoint", state.setpoint_C, "°C"],
                ["Room", state.room_temp_C, "°C"],
                ["Power draw", state.power_W, "W"],
                ["Power", state.power === undefined ? undefined : state.power ? "on" : "off", ""],
                ["Mode", state.mode === undefined ? undefined : state.mode === 1 ? "cool" : `raw ${state.mode}`, ""],
                ["Fan", state.fan === undefined ? undefined : FANS[state.fan] ?? `raw ${state.fan}`, ""],
              ].map(([label, value, unit]) => (
                <div key={label} className="rounded-lg bg-slate-900/70 px-3 py-2">
                  <div className="text-xs text-slate-500">{label}</div>
                  <div className="text-lg font-medium tabular-nums">
                    {value === undefined ? "—" : `${value}${unit}`}
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <p className="text-sm text-slate-500">No reading yet.</p>
          )}
          {state && (
            <details className="mt-3">
              <summary className="cursor-pointer text-xs text-slate-500">All datapoints</summary>
              <pre className="mt-2 overflow-x-auto rounded-lg bg-slate-950 p-3 text-xs text-slate-400">
                {JSON.stringify(state, null, 2)}
              </pre>
            </details>
          )}
        </Section>

        <Section title="Activity">
          {log.length === 0 ? (
            <p className="text-sm text-slate-500">Nothing sent yet.</p>
          ) : (
            <ul className="flex flex-col gap-2 text-xs">
              {log.map((e, i) => (
                <li key={i} className="rounded-lg bg-slate-900/70 px-3 py-2">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="text-slate-500">{e.at}</span>
                    <span className="rounded bg-slate-700 px-1.5 py-0.5 uppercase text-slate-300">
                      {e.transport}
                    </span>
                    <span className="font-medium text-slate-200">{e.cmd}</span>
                    {e.error && <span className="text-red-400">{e.error}</span>}
                  </div>
                  {e.hex && (
                    <div className="mt-1 break-all font-mono text-[11px] text-slate-500">{e.hex}</div>
                  )}
                </li>
              ))}
            </ul>
          )}
        </Section>

        <details className="rounded-xl border border-slate-800 bg-slate-800/30 p-4">
          <summary className="cursor-pointer text-xs font-semibold uppercase tracking-wider text-slate-500">
            Advanced — least tested
          </summary>
          <p className="mt-2 mb-3 text-xs text-slate-500">
            Timer and convertible are implemented but move no observable datapoint.
          </p>
          <div className="flex flex-wrap items-center gap-3">
            <label className="flex items-center gap-2 text-sm text-slate-300">
              Timer
              <input
                type="number"
                min="0"
                value={timerMin}
                onChange={(e) => setTimerMin(Number(e.target.value))}
                className="w-20 rounded-lg bg-slate-900 px-2 py-1.5 text-sm"
              />
              min
            </label>
            <Btn disabled={busy} onClick={() => send("timer", { minutes: timerMin, on: true })}>
              Set
            </Btn>
            <Btn disabled={busy} onClick={() => send("timer", { minutes: timerMin, on: false })}>
              Cancel
            </Btn>
            <label className="ml-4 flex items-center gap-2 text-sm text-slate-300">
              Convertible
              <input
                type="number"
                min="0"
                max="255"
                value={convertible}
                onChange={(e) => setConvertible(Number(e.target.value))}
                className="w-20 rounded-lg bg-slate-900 px-2 py-1.5 text-sm"
              />
            </label>
            <Btn disabled={busy} onClick={() => send("convertible", convertible)}>
              Send
            </Btn>
          </div>
        </details>
      </div>
    </div>
  );
}
