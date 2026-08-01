import React from "react";

/**
 * Three-state control: on / off / unknown.
 *
 * `value` is true, false, or undefined. Undefined means the AC never reported
 * this datapoint — the control shows "Unknown" with no position claimed rather
 * than defaulting to off. It stays usable: you can still send either command.
 *
 * Unknown must never be confusable with off, so it's dashed and carries the
 * word — not just a colour difference.
 *
 * Known state renders as a switch you flip. Unknown state renders as explicit
 * On/Off buttons instead: with no position to flip from, a single toggle could
 * only ever send one of the two commands.
 */
export default function Switch({ label, value, disabled, onSend, hint }) {
  const known = value !== undefined;
  const on = value === true;

  return (
    <div
      className="flex min-h-11 w-full items-center justify-between gap-3 rounded-xl
        border border-slate-800 bg-slate-900/40 px-3 py-2"
    >
      <span className="min-w-0">
        <span className="block truncate text-sm text-slate-200">{label}</span>
        <span
          className={`block text-[11px] ${
            known ? (on ? "text-sky-400" : "text-slate-500") : "text-amber-500/80"
          }`}
        >
          {known ? (on ? "On" : "Off") : hint || "Unknown"}
        </span>
      </span>

      {known ? (
        <button
          type="button"
          disabled={disabled}
          onClick={() => onSend(!on)}
          aria-label={`${label}: ${on ? "on" : "off"}`}
          className="shrink-0 disabled:cursor-not-allowed disabled:opacity-40"
        >
          <span
            className={`relative block h-6 w-11 rounded-full transition
              ${on ? "bg-sky-500" : "bg-slate-700"}`}
          >
            <span
              className={`absolute top-1 h-4 w-4 rounded-full transition-all
                ${on ? "left-6 bg-white" : "left-1 bg-slate-400"}`}
            />
          </span>
        </button>
      ) : (
        <span className="flex shrink-0 gap-1 rounded-lg border border-dashed
          border-amber-500/40 p-1">
          {[true, false].map((v) => (
            <button
              key={String(v)}
              type="button"
              disabled={disabled}
              onClick={() => onSend(v)}
              className="min-h-9 rounded-md px-2.5 text-xs font-medium text-slate-400
                transition hover:bg-slate-800 hover:text-slate-200
                disabled:cursor-not-allowed disabled:opacity-40"
            >
              {v ? "On" : "Off"}
            </button>
          ))}
        </span>
      )}
    </div>
  );
}
