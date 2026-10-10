// What the map's signals show (pure, tested with node --test): a status
// light per belt and a short signal at an output when a bag arrives there
// by mistake. Both only read the engine's state and events from the
// snapshots; the renderer draws them.

// A belt's light: its worst condition, from the snapshot. Faulty (error)
// wins over a warning (congestion of the belt, prolonged wait of a bag on
// it), which wins over the operator's stop; otherwise running. The light
// blinks while one of the belt's open alarms has not been acknowledged,
// and is steady once all of them have.
export function beltLights(snapshot) {
  const lights = new Map();
  const alarms = snapshot.alarms.filter((alarm) => alarm.state !== 'resolved');
  for (const belt of snapshot.belts) {
    // A bag's alarm names the belt the bag waits on.
    const own = alarms.filter((alarm) => alarm.element_id === belt.id);
    const warning = belt.congested || own.some((alarm) => alarm.severity === 'warning');
    lights.set(belt.id, {
      state: belt.faulty ? 'fault' : warning ? 'warning' : belt.stopped ? 'stopped' : 'running',
      blinking: own.some((alarm) => alarm.state === 'active'),
    });
  }
  return lights;
}

// How long an output signals a wrong arrival, in simulated seconds: it
// follows the displayed time, so it lines up with the bag reaching the
// output in the picture and stands still while paused.
export const WRONG_EXIT_SIGNAL_S = 3;
// Arrivals kept a little longer than the signal: the picture runs behind
// the newest snapshot (by up to a few simulated seconds at 5×).
const WRONG_EXIT_KEPT_S = WRONG_EXIT_SIGNAL_S + 10;

// The wrong arrivals still worth signalling, as { outputId, timeS }, after a
// snapshot: its `wrong_exit` events added, older ones dropped. A snapshot
// sends each event once per connection, and a reconnection resends only
// events far too old to be signalled again, if any.
export function addWrongExits(arrivals, snapshot) {
  const added = snapshot.events.filter((event) => event.kind === 'wrong_exit')
    .map((event) => ({ outputId: event.element_id, timeS: event.time_s }));
  return [...arrivals, ...added].filter((arrival) => arrival.timeS > snapshot.time_s - WRONG_EXIT_KEPT_S);
}

// Outputs signalling at a displayed time: output id → progress of its
// latest signal, from 0 (the arrival) towards 1 (the end).
export function wrongExitSignals(arrivals, timeS) {
  const signals = new Map();
  for (const { outputId, timeS: arrivedS } of arrivals) {
    const progress = (timeS - arrivedS) / WRONG_EXIT_SIGNAL_S;
    if (progress < 0 || progress >= 1) continue;
    signals.set(outputId, Math.min(progress, signals.get(outputId) ?? 1));
  }
  return signals;
}
