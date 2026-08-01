import React from "react";

export default function ActivityLog({ log, state }) {
  return (
    <div className="flex flex-col gap-2">
      <details className="rounded-2xl border border-slate-800 bg-slate-900/40 p-4">
        <summary className="cursor-pointer text-xs font-semibold uppercase tracking-wider text-slate-500">
          Activity {log.length > 0 && `(${log.length})`}
        </summary>
        {log.length === 0 ? (
          <p className="mt-3 text-sm text-slate-600">Nothing sent yet.</p>
        ) : (
          <ul className="mt-3 flex flex-col gap-2 text-xs">
            {log.map((e, i) => (
              <li key={i} className="rounded-lg bg-slate-950/60 px-3 py-2">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="text-slate-600">{e.at}</span>
                  <span className="rounded bg-slate-800 px-1.5 py-0.5 uppercase text-slate-400">
                    {e.transport}
                  </span>
                  <span className="font-medium text-slate-300">{e.cmd}</span>
                  {e.error && <span className="text-red-400">{e.error}</span>}
                </div>
                {e.hex && (
                  <div className="mt-1 break-all font-mono text-[11px] text-slate-600">
                    {e.hex}
                  </div>
                )}
              </li>
            ))}
          </ul>
        )}
      </details>

      <details className="rounded-2xl border border-slate-800 bg-slate-900/40 p-4">
        <summary className="cursor-pointer text-xs font-semibold uppercase tracking-wider text-slate-500">
          Raw datapoints
        </summary>
        {state ? (
          <pre className="mt-3 overflow-x-auto rounded-lg bg-slate-950 p-3 text-xs text-slate-400">
            {JSON.stringify(state, null, 2)}
          </pre>
        ) : (
          <p className="mt-3 text-sm text-slate-600">No reading yet.</p>
        )}
      </details>
    </div>
  );
}
