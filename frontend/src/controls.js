// Top bar: start/pause, reset and speed buttons, connection state,
// simulated time, and the engine's indicators (KPIs) under it.
//
// The indicators are the engine's, copied from the snapshot as they are: the
// page never computes its own version of the statistics, it only formats
// them.

// Key in the snapshot's stats, name and what it means (shown as a tooltip).
// Generated stays next to Waiting and Admitted for the counter rules:
// Generated = Admitted + Waiting; Admitted = Delivered + Wrong exits + In transit.
const INDICATORS = [
  ['generated', 'Generated', 'Bags created at the check-in desks'],
  ['waiting', 'Waiting', 'Generated but not yet admitted: queued at the check-in desks'],
  ['admitted', 'Admitted', 'Bags that entered the plant'],
  ['in_transit', 'In transit', 'Admitted bags still in the plant, moving or stopped'],
  ['correctly_delivered', 'Delivered', 'Bags that exited at their own destination'],
  ['misdelivered', 'Wrong exits', 'Bags that exited at another destination'],
  ['mean_travel_time_s', 'Mean time', 'Mean time from admission to exit, wrong exits included'],
  ['throughput', 'Throughput', 'Correct deliveries in the last 60 simulated seconds'],
  ['errors', 'Errors', 'Error occurrences since the start of the run'],
  ['warnings', 'Warnings', 'Warning occurrences since the start of the run'],
];

// The indicators of a snapshot's stats as { key, name, help, value } with
// value as text, in display order.
export function indicators(stats) {
  return INDICATORS.map(([key, name, help]) => ({ key, name, help, value: formatIndicator(key, stats[key]) }));
}

function formatIndicator(key, value) {
  if (key === 'mean_travel_time_s') return value === null ? '—' : `${value.toFixed(2)} s`;
  if (key === 'throughput') return `${value} / 60 s`;
  return String(value);
}

export function formatTime(seconds) {
  const minutes = Math.floor(seconds / 60);
  const rest = (seconds - minutes * 60).toFixed(2).padStart(5, '0');
  return `${String(minutes).padStart(2, '0')}:${rest}`;
}

// What the start/pause button shows for a snapshot. After a click on Reset
// the server is about to start a new, paused run, but snapshots of the old
// run (still running) can arrive in between: until a snapshot of another
// run arrives (`resetFromRun` is the run reset), the button stays on Start,
// so a click right after Reset starts the new run instead of pausing it.
export function toggleState(snapshot, resetFromRun = null) {
  if (resetFromRun !== null && snapshot.run === resetFromRun) {
    return { running: false, label: 'Start' };
  }
  const running = snapshot.running;
  return { running, label: running ? 'Pause' : snapshot.tick === 0 ? 'Start' : 'Resume' };
}

export function createControls({ onCommand }) {
  const button = document.querySelector('#toggle');
  const reset = document.querySelector('#reset');
  const speeds = [...document.querySelectorAll('.speeds button')];
  const connection = document.querySelector('#connection');
  const time = document.querySelector('#time');
  const counters = document.querySelector('#counters');

  const values = {};
  for (const [key, name, help] of INDICATORS) {
    const item = document.createElement('div');
    const term = document.createElement('dt');
    const value = document.createElement('dd');
    item.title = help;
    term.textContent = name;
    value.textContent = '—';
    item.append(term, value);
    counters.append(item);
    values[key] = value;
  }

  let running = false;
  let run = null;           // run of the newest snapshot
  let resetFromRun = null;  // run being reset, until a snapshot of the new one arrives
  function showToggle(state) {
    running = state.running;
    button.textContent = state.label;
  }
  button.addEventListener('click', () => onCommand({ type: running ? 'pause' : 'start' }));
  reset.addEventListener('click', () => {
    onCommand({ type: 'reset' });
    if (run !== null) {
      resetFromRun = run;
      showToggle({ running: false, label: 'Start' });
    }
  });
  for (const speed of speeds) {
    speed.addEventListener('click', () => onCommand({ type: 'set_speed', speed: Number(speed.dataset.speed) }));
  }

  return {
    setConnected(connected) {
      for (const control of [button, reset, ...speeds]) control.disabled = !connected;
      connection.textContent = connected ? 'Connected' : 'Disconnected · retrying…';
      connection.dataset.state = connected ? 'connected' : 'disconnected';
      // A reset sent on a lost connection may never be applied.
      if (!connected) resetFromRun = null;
    },
    setSnapshot(snapshot) {
      if (snapshot.run !== resetFromRun) resetFromRun = null;
      run = snapshot.run;
      showToggle(toggleState(snapshot, resetFromRun));
      time.textContent = `${formatTime(snapshot.time_s)} · tick ${snapshot.tick}`;
      for (const speed of speeds) {
        speed.setAttribute('aria-pressed', String(Number(speed.dataset.speed) === snapshot.speed));
      }
      for (const { key, value } of indicators(snapshot.stats)) values[key].textContent = value;
    },
  };
}
