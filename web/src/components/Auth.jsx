import React, { useState } from "react";
import { api } from "../api.js";
import DeviceList from "./DeviceList.jsx";

/**
 * Cloud sign-in (phone OTP) and the device list.
 *
 * Only cloud transport needs this — BLE talks to the AC directly, so the panel
 * stays usable without ever signing in.
 */
export default function Auth({ session, onSession, onBack }) {
  const [phone, setPhone] = useState("");
  const [otp, setOtp] = useState("");
  const [stage, setStage] = useState("phone"); // phone -> otp
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  const input =
    "min-h-11 w-full rounded-xl border border-slate-800 bg-slate-950 px-3 " +
    "text-slate-100 placeholder:text-slate-600 focus:border-sky-600 focus:outline-none";
  const primary =
    "min-h-11 w-full rounded-xl bg-sky-500 px-4 font-medium text-white transition " +
    "hover:bg-sky-400 disabled:cursor-not-allowed disabled:opacity-40";

  async function run(fn) {
    setBusy(true);
    setError(null);
    try {
      await fn();
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }

  const sendOtp = () =>
    run(async () => {
      await api("/api/send-otp", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ phone }),
      });
      setStage("otp");
    });

  const verifyOtp = () =>
    run(async () => {
      await api("/api/verify-otp", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ phone, otp }),
      });
      const s = await api("/api/session");
      onSession(s);
    });

  return (
    <div className="mx-auto flex min-h-screen max-w-md flex-col justify-center gap-4 px-4 py-8">
      <div className="rounded-2xl border border-slate-800 bg-slate-900/50 p-6">
        <h1 className="text-xl font-semibold text-slate-100">Cloud account</h1>
        <p className="mt-1 text-sm text-slate-500">
          Needed for cloud transport. BLE works without it.
        </p>

        {session?.loggedIn ? (
          <div className="mt-5 flex flex-col gap-4">
            <div className="rounded-xl bg-slate-950/60 px-3 py-2 text-sm">
              <span className="text-slate-500">Signed in as </span>
              <span className="text-slate-200">{session.phone || "unknown"}</span>
            </div>
            <DeviceList />
          </div>
        ) : (
          <div className="mt-5 flex flex-col gap-3">
            <label className="text-xs uppercase tracking-wider text-slate-500">
              Phone
              <input
                className={`mt-1 ${input}`}
                value={phone}
                onChange={(e) => setPhone(e.target.value)}
                placeholder="+91…"
                inputMode="tel"
                disabled={stage === "otp"}
              />
            </label>

            {stage === "phone" ? (
              <button className={primary} disabled={busy || !phone} onClick={sendOtp}>
                {busy ? "Sending…" : "Send code"}
              </button>
            ) : (
              <>
                <label className="text-xs uppercase tracking-wider text-slate-500">
                  Code
                  <input
                    className={`mt-1 tracking-[0.3em] ${input}`}
                    value={otp}
                    onChange={(e) => setOtp(e.target.value)}
                    placeholder="······"
                    inputMode="numeric"
                  />
                </label>
                <button className={primary} disabled={busy || !otp} onClick={verifyOtp}>
                  {busy ? "Verifying…" : "Verify"}
                </button>
                <button
                  className="text-xs text-slate-500 hover:text-slate-300"
                  onClick={() => {
                    setStage("phone");
                    setOtp("");
                  }}
                >
                  Use a different number
                </button>
              </>
            )}
          </div>
        )}

        {error && (
          <div className="mt-4 rounded-xl border border-red-900/60 bg-red-950/50 px-3 py-2 text-sm text-red-300">
            {error}
          </div>
        )}
      </div>

      <button
        onClick={onBack}
        className="min-h-11 rounded-xl border border-slate-800 text-sm text-slate-400
          transition hover:bg-slate-900 hover:text-slate-200"
      >
        Back to controls
      </button>
    </div>
  );
}
