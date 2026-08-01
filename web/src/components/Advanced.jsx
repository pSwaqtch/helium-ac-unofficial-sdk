import React, { useState } from "react";

/**
 * Timer and convertible.
 *
 * These are command arguments, not device state — nothing the AC reports can
 * ever populate them, so unlike everything else in the panel they carry
 * prefills. Neither moves an observable datapoint (PROTOCOL §7).
 */
export default function Advanced({ busy, onSend }) {
  const [timerMin, setTimerMin] = useState(30);
  const [convertible, setConvertible] = useState(0);

  const btn =
    "min-h-11 rounded-lg bg-slate-800 px-3 text-sm text-slate-200 transition " +
    "hover:bg-slate-700 disabled:cursor-not-allowed disabled:opacity-40";
  const input =
    "w-20 min-h-11 rounded-lg border border-slate-800 bg-slate-950 px-2 text-sm " +
    "text-slate-200 tabular-nums";

  return (
    <details className="rounded-2xl border border-slate-800 bg-slate-900/40 p-4">
      <summary className="cursor-pointer text-xs font-semibold uppercase tracking-wider text-slate-500">
        Advanced — least tested
      </summary>
      <p className="mt-2 mb-3 text-xs text-slate-600">
        Timer and convertible are implemented but move no observable datapoint, so
        the AC never reports them back.
      </p>
      <div className="flex flex-wrap items-center gap-3">
        <label className="flex items-center gap-2 text-sm text-slate-300">
          Timer
          <input
            type="number"
            min="0"
            value={timerMin}
            onChange={(e) => setTimerMin(Number(e.target.value))}
            className={input}
          />
          min
        </label>
        <button
          disabled={busy}
          onClick={() => onSend("timer", { minutes: timerMin, on: true })}
          className={btn}
        >
          Set
        </button>
        <button
          disabled={busy}
          onClick={() => onSend("timer", { minutes: timerMin, on: false })}
          className={btn}
        >
          Cancel
        </button>

        <label className="flex items-center gap-2 text-sm text-slate-300 sm:ml-4">
          Convertible
          <input
            type="number"
            min="0"
            max="255"
            value={convertible}
            onChange={(e) => setConvertible(Number(e.target.value))}
            className={input}
          />
        </label>
        <button
          disabled={busy}
          onClick={() => onSend("convertible", convertible)}
          className={btn}
        >
          Send
        </button>
      </div>
    </details>
  );
}
