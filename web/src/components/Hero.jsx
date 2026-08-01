import React from "react";

const MIN_C = 16;
const MAX_C = 30;

function Stat({ label, value, unit }) {
  const known = value !== undefined && value !== null;
  return (
    <div>
      <div className="text-[11px] uppercase tracking-wider text-slate-500">{label}</div>
      <div
        className={`text-lg font-semibold tabular-nums ${
          known ? "text-slate-200" : "text-slate-600"
        }`}
      >
        {known ? `${value}${unit}` : "—"}
      </div>
    </div>
  );
}

/** Power reads on / off / unknown — never a pair of buttons with no state. */
function PowerControl({ power, busy, onSend }) {
  const known = power !== undefined;
  return (
    <div className="flex items-center gap-3">
      <span
        className={`flex items-center gap-2 text-sm font-medium ${
          known ? (power ? "text-emerald-400" : "text-slate-500") : "text-amber-500/80"
        }`}
      >
        <span
          className={`h-2.5 w-2.5 rounded-full ${
            known
              ? power
                ? "bg-emerald-400"
                : "bg-slate-600"
              : "border border-dashed border-amber-500/70"
          }`}
        />
        {known ? (power ? "On" : "Off") : "Unknown"}
      </span>
      <div className="flex gap-1 rounded-lg bg-slate-900/60 p-1">
        <button
          disabled={busy}
          onClick={() => onSend(true)}
          className={`min-h-9 rounded-md px-3 text-sm font-medium transition
            disabled:opacity-40 ${
              known && power
                ? "bg-emerald-500/90 text-white"
                : "text-slate-400 hover:bg-slate-800 hover:text-slate-200"
            }`}
        >
          On
        </button>
        <button
          disabled={busy}
          onClick={() => onSend(false)}
          className={`min-h-9 rounded-md px-3 text-sm font-medium transition
            disabled:opacity-40 ${
              known && !power
                ? "bg-slate-600 text-white"
                : "text-slate-400 hover:bg-slate-800 hover:text-slate-200"
            }`}
        >
          Off
        </button>
      </div>
    </div>
  );
}

export default function Hero({ state, setpoint, busy, onPower, onBump }) {
  // no setpoint read yet means nothing to step from — the buttons stay dead
  const known = setpoint !== null && setpoint !== undefined;

  return (
    <section className="rounded-2xl border border-slate-800 bg-gradient-to-b from-slate-800/60 to-slate-900/60 p-5 sm:p-6">
      <div className="flex flex-col gap-6 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex items-center gap-5">
          <button
            disabled={busy || !known || setpoint <= MIN_C}
            onClick={() => onBump(-1, MIN_C, MAX_C)}
            aria-label="Lower setpoint"
            className="flex h-14 w-14 items-center justify-center rounded-full border
              border-slate-700 bg-slate-800 text-2xl text-slate-200 transition
              hover:bg-slate-700 disabled:cursor-not-allowed disabled:opacity-30"
          >
            −
          </button>

          <div className="text-center">
            <div
              className={`text-6xl font-light tabular-nums leading-none sm:text-7xl ${
                known ? "text-white" : "text-slate-700"
              }`}
            >
              {known ? setpoint : "—"}
              <span className="align-top text-3xl">°</span>
            </div>
            <div className="mt-1 text-[11px] uppercase tracking-wider text-slate-500">
              {known ? "setpoint" : "setpoint unknown"}
            </div>
          </div>

          <button
            disabled={busy || !known || setpoint >= MAX_C}
            onClick={() => onBump(1, MIN_C, MAX_C)}
            aria-label="Raise setpoint"
            className="flex h-14 w-14 items-center justify-center rounded-full border
              border-slate-700 bg-slate-800 text-2xl text-slate-200 transition
              hover:bg-slate-700 disabled:cursor-not-allowed disabled:opacity-30"
          >
            +
          </button>
        </div>

        <div className="flex flex-col items-start gap-4 sm:items-end">
          <PowerControl power={state?.power} busy={busy} onSend={onPower} />
          <div className="flex gap-6">
            <Stat label="Room" value={state?.room_temp_C} unit="°" />
            <Stat label="Draw" value={state?.power_W} unit="W" />
          </div>
        </div>
      </div>
    </section>
  );
}
