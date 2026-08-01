import React, { useEffect, useState } from "react";
import { api } from "./api.js";
import { useAcState } from "./useAcState.js";
import Hero from "./components/Hero.jsx";
import Segmented from "./components/Segmented.jsx";
import Switch from "./components/Switch.jsx";
import TransportBar from "./components/TransportBar.jsx";
import ActivityLog from "./components/ActivityLog.jsx";
import Advanced from "./components/Advanced.jsx";
import Auth from "./components/Auth.jsx";

const FANS = ["auto", "low", "medium", "high"];
// DP4: 1 is cool, confirmed live. Anything else is unrecognised, not "heat".
const MODES = [
  { label: "cool", value: 1, cmd: "cool" },
  { label: "heat", value: 2, cmd: "heat" },
];

export default function App() {
  const [transport, setTransport] = useState(
    () => localStorage.getItem("transport") || "cloud"
  );
  const [screen, setScreen] = useState("panel");
  const [session, setSession] = useState(null);

  const ac = useAcState(transport);

  useEffect(() => localStorage.setItem("transport", transport), [transport]);

  useEffect(() => {
    api("/api/session").then(setSession).catch(() => {});
  }, [screen]);

  if (screen === "auth") {
    return (
      <Auth
        session={session}
        onSession={setSession}
        onBack={() => setScreen("panel")}
      />
    );
  }

  const { state } = ac;
  // an unrecognised mode value is unknown — we don't map it onto a label
  const modeValue = MODES.some((m) => m.value === state?.mode) ? state.mode : undefined;
  const fanValue = state?.fan !== undefined && FANS[state.fan] !== undefined
    ? state.fan
    : undefined;

  return (
    <div className="min-h-screen bg-slate-950 px-4 py-6 text-slate-100">
      <div className="mx-auto flex max-w-3xl flex-col gap-4">
        <header className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h1 className="text-xl font-semibold tracking-tight">Helium AC</h1>
            <p className="text-xs text-slate-500">
              {transport === "ble" ? "Direct BLE" : "Cloud MQTT"}
            </p>
          </div>
          <button
            onClick={() => setScreen("auth")}
            className="min-h-9 rounded-xl border border-slate-800 px-3 text-sm
              text-slate-400 transition hover:bg-slate-900 hover:text-slate-200"
          >
            {session?.loggedIn ? "Account" : "Sign in"}
          </button>
        </header>

        <TransportBar
          transport={transport}
          setTransport={setTransport}
          bleConnected={ac.bleConnected}
          busy={ac.busy}
          onBle={ac.ble}
          readAt={ac.readAt}
          refreshing={ac.refreshing}
          onRead={() => ac.readState()}
        />

        {ac.error && (
          <div className="rounded-xl border border-red-900/60 bg-red-950/50 px-4 py-2 text-sm text-red-300">
            {ac.error}
          </div>
        )}

        <Hero
          state={state}
          setpoint={ac.setpoint}
          busy={ac.busy}
          onPower={(v) => ac.send("power", v)}
          onBump={ac.bumpTemp}
        />

        <div className="grid gap-4 sm:grid-cols-2">
          <div className="rounded-2xl border border-slate-800 bg-slate-900/40 p-4">
            <Segmented
              label="Mode"
              options={MODES}
              value={modeValue}
              disabled={ac.busy}
              onSelect={(o) => ac.send("mode", o.cmd)}
            />
          </div>
          <div className="rounded-2xl border border-slate-800 bg-slate-900/40 p-4">
            <Segmented
              label="Fan"
              options={FANS.map((f, i) => ({ label: f, value: i, cmd: f }))}
              value={fanValue}
              disabled={ac.busy}
              onSelect={(o) => ac.send("fan", o.cmd)}
            />
          </div>
        </div>

        <section className="rounded-2xl border border-slate-800 bg-slate-900/40 p-4">
          <h2 className="mb-3 text-xs font-medium uppercase tracking-wider text-slate-500">
            Airflow & comfort
          </h2>
          <div className="grid gap-2 sm:grid-cols-2">
            {/* only turbo and vertical swing are ever reported back, and only over BLE */}
            <Switch
              label="Vertical swing"
              value={state?.vertical_swing === undefined ? undefined : !!state.vertical_swing}
              disabled={ac.busy}
              onSend={(v) => ac.send("verticalSwing", v)}
            />
            <Switch
              label="Turbo"
              value={state?.turbo === undefined ? undefined : !!state.turbo}
              disabled={ac.busy}
              onSend={(v) => ac.send("turbo", v)}
            />
            <Switch
              label="Horizontal swing"
              value={undefined}
              hint="Never reported"
              disabled={ac.busy}
              onSend={(v) => ac.send("horizontalSwing", v)}
            />
            <Switch
              label="Sleep"
              value={undefined}
              hint="Never reported"
              disabled={ac.busy}
              onSend={(v) => ac.send("sleep", v)}
            />
            <Switch
              label="Display"
              value={undefined}
              hint="Never reported"
              disabled={ac.busy}
              onSend={(v) => ac.send("display", v)}
            />
            <Switch
              label="Silent"
              value={undefined}
              hint="Never reported"
              disabled={ac.busy}
              onSend={(v) => ac.send("silent", v)}
            />
          </div>
        </section>

        <Advanced busy={ac.busy} onSend={ac.send} />
        <ActivityLog log={ac.log} state={state} />
      </div>
    </div>
  );
}
