import React from "react";

/**
 * Segmented picker with an explicit unknown state.
 *
 * When `value` is undefined the AC reported nothing for this control. That is
 * rendered as a dashed outline plus an "unknown" caption — not as "all segments
 * inactive", which would read identically to "we know it's none of these".
 */
export default function Segmented({ label, options, value, disabled, onSelect }) {
  const known = value !== undefined;

  return (
    <div>
      <div className="mb-2 flex items-baseline justify-between gap-2">
        <span className="text-xs font-medium uppercase tracking-wider text-slate-500">
          {label}
        </span>
        {!known && (
          <span className="text-[11px] text-amber-500/80">unknown</span>
        )}
      </div>

      <div
        className={`flex gap-1 rounded-xl p-1 ${
          known
            ? "bg-slate-900/60"
            : "border border-dashed border-amber-500/40 bg-transparent"
        }`}
      >
        {options.map((o) => {
          const active = known && o.value === value;
          return (
            <button
              key={o.label}
              type="button"
              disabled={disabled}
              onClick={() => onSelect(o)}
              className={`min-h-11 flex-1 rounded-lg px-2 text-sm font-medium capitalize
                transition disabled:cursor-not-allowed disabled:opacity-40
                ${
                  active
                    ? "bg-sky-500 text-white shadow"
                    : "text-slate-400 hover:bg-slate-800 hover:text-slate-200"
                }`}
            >
              {o.label}
            </button>
          );
        })}
      </div>
    </div>
  );
}
