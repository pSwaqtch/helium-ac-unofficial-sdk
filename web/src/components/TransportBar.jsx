import React from "react";

/**
 * Transport pill plus the BLE link controls.
 *
 * The BLE row only exists when BLE is selected, but it lives inside this same
 * container so switching transport doesn't reflow the whole page.
 */
export default function TransportBar({
  transport, setTransport, bleConnected, busy, onBle, readAt, refreshing, onRead,
}) {
  return (
    <div className="rounded-2xl border border-slate-800 bg-slate-900/40 p-2">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex rounded-xl bg-slate-900/70 p-1">
          {["ble", "cloud"].map((t) => (
            <button
              key={t}
              onClick={() => setTransport(t)}
              className={`min-h-9 rounded-lg px-4 text-sm font-medium uppercase tracking-wide
                transition ${
                  transport === t
                    ? "bg-sky-500 text-white"
                    : "text-slate-400 hover:text-slate-200"
                }`}
            >
              {t}
            </button>
          ))}
        </div>

        <div className="flex items-center gap-2 px-1">
          <span className="text-[11px] text-slate-500">
            {refreshing ? "reading…" : readAt ? `read ${readAt}` : "not read yet"}
          </span>
          <button
            disabled={busy || refreshing}
            onClick={onRead}
            className="min-h-9 rounded-lg border border-slate-700 px-3 text-sm
              text-slate-300 transition hover:bg-slate-800 disabled:opacity-40"
          >
            Refresh
          </button>
        </div>
      </div>

      {transport === "ble" && (
        <div className="mt-2 flex flex-wrap items-center justify-between gap-2
          rounded-xl bg-slate-900/60 px-3 py-2">
          <span className="text-xs text-slate-400">
            Link{" "}
            <span className={bleConnected ? "text-emerald-400" : "text-slate-500"}>
              {bleConnected ? "connected" : "not connected"}
            </span>
            <span className="ml-2 text-slate-600">
              needs the phone app disconnected
            </span>
          </span>
          <div className="flex gap-2">
            <button
              disabled={busy}
              onClick={() => onBle("connect")}
              className="min-h-9 rounded-lg bg-slate-800 px-3 text-sm text-slate-200
                transition hover:bg-slate-700 disabled:opacity-40"
            >
              Connect
            </button>
            <button
              disabled={busy}
              onClick={() => onBle("disconnect")}
              className="min-h-9 rounded-lg bg-slate-800 px-3 text-sm text-slate-200
                transition hover:bg-slate-700 disabled:opacity-40"
            >
              Disconnect
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
