// Top bar: start/pause button, connection state, simulated time and counters.
//
// The counters are the engine's, copied from the snapshot as they are: the
// page never computes its own version of the statistics.

const COUNTERS = [
  ['generated', 'Generated'],
  ['waiting', 'Waiting'],
  ['admitted', 'Admitted'],
  ['in_transit', 'In transit'],
  ['correctly_delivered', 'Delivered'],
  ['misdelivered', 'Misdelivered'],
];

export function formatTime(seconds) {
  const minutes = Math.floor(seconds / 60);
  const rest = (seconds - minutes * 60).toFixed(2).padStart(5, '0');
  return `${String(minutes).padStart(2, '0')}:${rest}`;
}

export function createControls({ onCommand }) {
  const button = document.querySelector('#toggle');
  const connection = document.querySelector('#connection');
  const time = document.querySelector('#time');
  const counters = document.querySelector('#counters');

  const values = {};
  for (const [key, name] of [...COUNTERS, ['mean_travel_time_s', 'Mean time']]) {
    const item = document.createElement('div');
    const term = document.createElement('dt');
    const value = document.createElement('dd');
    term.textContent = name;
    value.textContent = '—';
    item.append(term, value);
    counters.append(item);
    values[key] = value;
  }

  let running = false;
  button.addEventListener('click', () => onCommand({ type: running ? 'pause' : 'start' }));

  return {
    setConnected(connected) {
      button.disabled = !connected;
      connection.textContent = connected ? 'Connected' : 'Disconnected · retrying…';
      connection.dataset.state = connected ? 'connected' : 'disconnected';
    },
    setSnapshot(snapshot) {
      running = snapshot.running;
      button.textContent = running ? 'Pause' : snapshot.tick === 0 ? 'Start' : 'Resume';
      time.textContent = `${formatTime(snapshot.time_s)} · tick ${snapshot.tick}`;
      for (const [key] of COUNTERS) values[key].textContent = snapshot.stats[key];
      const mean = snapshot.stats.mean_travel_time_s;
      values.mean_travel_time_s.textContent = mean === null ? '—' : `${mean.toFixed(2)} s`;
    },
  };
}
