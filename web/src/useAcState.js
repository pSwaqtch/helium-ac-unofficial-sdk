import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "./api.js";

/**
 * Owns the AC's reported state and the command path.
 *
 * The panel never displays a value the AC didn't report, so `state` starts null
 * and `setpoint` starts null — there is no initial guess to fall back to.
 */
export function useAcState(transport) {
  const [state, setState] = useState(null);
  const [readAt, setReadAt] = useState(null);
  const [setpoint, setSetpoint] = useState(null);
  const [busy, setBusy] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState(null);
  const [log, setLog] = useState([]);
  const [bleConnected, setBleConnected] = useState(false);

  const note = useCallback((entry) => {
    setLog((l) =>
      [{ at: new Date().toLocaleTimeString(), ...entry }, ...l].slice(0, 12)
    );
  }, []);

  const syncBle = useCallback(() => {
    api("/api/ble/status")
      .then((s) => setBleConnected(s.connected))
      .catch(() => {});
  }, []);

  const readState = useCallback(
    async ({ quiet = false } = {}) => {
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
        if (res.state.setpoint_C !== undefined) setSetpoint(res.state.setpoint_C);
        if (!quiet) note({ cmd: "read state", transport: res.transport });
      } catch (e) {
        // a background refresh failing shouldn't stomp on the UI with an error
        if (!quiet) setError(e.message);
        // a BLE read failing usually means the link dropped (phone app grabbed the
        // AC, or out of range) — resync the flag so the UI stops claiming connected
        if (transport === "ble") syncBle();
      } finally {
        setRefreshing(false);
      }
    },
    [transport, note, syncBle]
  );

  // keep a stable reference for the post-command refresh timer
  const readRef = useRef(readState);
  readRef.current = readState;

  const send = useCallback(
    async (field, value) => {
      setBusy(true);
      setError(null);
      try {
        const res = await api(`/api/ac/command?transport=${transport}`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ [field]: value }),
        });
        note({
          cmd: `${field}=${JSON.stringify(value)}`,
          transport: res.transport,
          hex: res.payload,
        });
        // let the unit settle, then refresh so the readout reflects what we just did
        setTimeout(() => readRef.current({ quiet: true }), 1500);
      } catch (e) {
        setError(e.message);
        note({ cmd: `${field}=${JSON.stringify(value)}`, transport, error: e.message });
      } finally {
        setBusy(false);
      }
    },
    [transport, note]
  );

  const ble = useCallback(
    async (action) => {
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
    },
    [note]
  );

  useEffect(() => syncBle(), [syncBle]);

  // pull current state on load and whenever the transport changes, so the panel
  // always opens showing where the AC actually is
  useEffect(() => {
    readState({ quiet: true });
  }, [readState]);

  /** Send a setpoint delta. Refuses when no setpoint has been read — there is
   *  nothing to increment from and we won't invent a starting point. */
  const bumpTemp = useCallback(
    (delta, min, max) => {
      if (setpoint === null) return;
      const next = Math.min(max, Math.max(min, setpoint + delta));
      setSetpoint(next);
      send("temperature", next);
    },
    [setpoint, send]
  );

  return {
    state, readAt, setpoint, busy, refreshing, error, log, bleConnected,
    readState, send, ble, bumpTemp, setError,
  };
}
