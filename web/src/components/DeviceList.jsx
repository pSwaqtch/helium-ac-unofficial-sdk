import React, { useEffect, useState } from "react";
import { api } from "../api.js";

/**
 * Devices from both backends.
 *
 * The hoags response shape isn't pinned down (server.py wraps it as {resp}), so
 * anything we can't confidently name is shown as raw JSON rather than guessed at.
 */
export default function DeviceList() {
  const [devices, setDevices] = useState(null);
  const [hoags, setHoags] = useState(null);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);

  function load() {
    setBusy(true);
    setError(null);
    Promise.allSettled([api("/api/devices"), api("/api/hoags-devices")])
      .then(([d, h]) => {
        if (d.status === "fulfilled") setDevices(d.value);
        if (h.status === "fulfilled") setHoags(h.value);
        if (d.status === "rejected" && h.status === "rejected") {
          setError(d.reason.message);
        }
      })
      .finally(() => setBusy(false));
  }

  useEffect(load, []);

  const list = Array.isArray(devices) ? devices : devices?.devices;

  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-center justify-between">
        <span className="text-xs font-semibold uppercase tracking-wider text-slate-500">
          Devices
        </span>
        <button
          onClick={load}
          disabled={busy}
          className="min-h-9 rounded-lg border border-slate-800 px-3 text-xs
            text-slate-400 transition hover:bg-slate-800 disabled:opacity-40"
        >
          {busy ? "Loading…" : "Reload"}
        </button>
      </div>

      {error && <p className="text-sm text-red-400">{error}</p>}

      {Array.isArray(list) && list.length > 0 ? (
        <ul className="flex flex-col gap-2">
          {list.map((d, i) => (
            <li key={d.id || d.deviceId || i} className="rounded-xl bg-slate-950/60 px-3 py-2">
              <div className="text-sm text-slate-200">
                {d.name || d.deviceName || d.id || d.deviceId || `Device ${i + 1}`}
              </div>
              {(d.id || d.deviceId) && (
                <div className="font-mono text-[11px] text-slate-600">
                  {d.id || d.deviceId}
                </div>
              )}
            </li>
          ))}
        </ul>
      ) : (
        !busy && !error && <p className="text-sm text-slate-600">No devices listed.</p>
      )}

      {(devices || hoags) && (
        <details>
          <summary className="cursor-pointer text-[11px] text-slate-600">
            Raw response
          </summary>
          <pre className="mt-2 overflow-x-auto rounded-lg bg-slate-950 p-3 text-[11px] text-slate-500">
            {JSON.stringify({ devices, hoags }, null, 2)}
          </pre>
        </details>
      )}
    </div>
  );
}
