// Top bar (start/pause, reset and speed buttons, connection state,
// simulated time), the engine's indicators (KPIs) on the Indicators page and
// the key ones in the strip under the map.
//
// The indicators are the engine's, copied from the snapshot as they are: the
// page never computes its own version of the statistics, it only formats
// them.

// "1 fault", "2 faults".
export const count = (n, noun) => `${n} ${noun}${n === 1 ? '' : 's'}`;

// Indicators in three groups. Each one: key in the snapshot's stats, name,
// a short caption shown under the value (text, or a function of the stats
// that formats the engine's own breakdown), and what it means (tooltip).
// The counter rules read along the first two groups:
// Generated = Admitted + Waiting; Admitted = Delivered + Wrong exits + In transit.
export const INDICATOR_GROUPS = [
  {
    id: 'flow',
    title: 'Bag flow',
    items: [
      ['generated', 'Generated', 'at the desks', 'Bags created at the check-in desks'],
      ['waiting', 'Waiting', 'queued at the desks', 'Generated but not yet admitted into the plant'],
      ['admitted', 'Admitted', 'entered the plant', 'Bags that entered the plant'],
      ['in_transit', 'In transit', 'on the belts', 'Admitted bags still in the plant, moving or stopped'],
    ],
  },
  {
    id: 'deliveries',
    title: 'Deliveries',
    items: [
      ['correctly_delivered', 'Delivered', 'at their own exit', 'Bags that exited at their own destination'],
      ['misdelivered', 'Wrong exits', 'at another exit', 'Bags that exited at another destination'],
      ['throughput', 'Throughput', 'delivered in the last 60 s',
        'Correct deliveries in the last 60 simulated seconds'],
      ['mean_travel_time_s', 'Mean travel time', 'admission to exit',
        'Mean time from admission to exit of every exited bag, wrong exits included'],
    ],
  },
  {
    id: 'alarms',
    title: 'Alarms',
    items: [
      ['active_errors', 'Active errors', 'open now',
        'Error alarms open now (faults not yet repaired), acknowledged or not'],
      ['active_warnings', 'Active warnings', 'open now',
        'Warning alarms open now (congestions, prolonged waits), acknowledged or not'],
      ['errors', 'Errors', (stats) => `${count(stats.faults, 'fault')} · ${count(stats.wrong_sortings, 'wrong sorting')}`,
        'Error occurrences since the start of the run: faults and wrong sortings'],
      ['warnings', 'Warnings',
        (stats) => `${count(stats.congestions, 'congestion')} · ${count(stats.prolonged_waits, 'prolonged wait')}`,
        'Warning occurrences since the start of the run: congestions and prolonged waits'],
    ],
  },
];

// Indicators that call for attention when above zero. The occurrences since
// the start are not: they never go back down, the active alarms do.
const ALERTS = { misdelivered: 'warning', active_warnings: 'warning', active_errors: 'error' };

// The indicators of a snapshot's stats, in display order, as
// { group, key, name, caption, help, value, alert } with value as text and
// alert 'warning', 'error' or null.
export function indicators(stats) {
  return INDICATOR_GROUPS.flatMap((group) => group.items.map(([key, name, caption, help]) => ({
    group: group.id,
    key,
    name,
    caption: typeof caption === 'function' ? caption(stats) : caption,
    help,
    value: formatIndicator(key, stats[key]),
    alert: ALERTS[key] && stats[key] > 0 ? ALERTS[key] : null,
  })));
}

// The indicators always in view, in the strip under the map: the queue,
// the flow, the outcome and the open alarms, as [key, page it opens]. The
// strip shows the same values as the Indicators page.
export const KEY_INDICATORS = [
  ['waiting', 'stats'], ['in_transit', 'stats'], ['correctly_delivered', 'stats'], ['misdelivered', 'stats'],
  ['throughput', 'stats'], ['active_errors', 'alarms'], ['active_warnings', 'alarms'],
];

function formatIndicator(key, value) {
  if (key === 'mean_travel_time_s') return value === null ? '—' : `${value.toFixed(1)} s`;
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

export function createControls({ onCommand, onOpen = () => {} }) {
  const button = document.querySelector('#toggle');
  const label = button.querySelector('.label');
  const reset = document.querySelector('#reset');
  const speeds = [...document.querySelectorAll('.speeds button')];
  const connection = document.querySelector('#connection');
  const time = document.querySelector('#time');
  const tick = document.querySelector('#tick');
  const counters = document.querySelector('#counters');
  const strip = document.querySelector('#kpis');

  // One tile per indicator on the Indicators page: name, value and caption, grouped.
  const values = {};
  const notes = {};
  const tiles = {};
  for (const group of INDICATOR_GROUPS) {
    const section = document.createElement('section');
    section.className = 'indicator-group';
    section.dataset.group = group.id;
    const heading = document.createElement('h4');
    heading.textContent = group.title;
    const list = document.createElement('dl');
    for (const [key, name, caption, help] of group.items) {
      const tile = document.createElement('div');
      const term = document.createElement('dt');
      const value = document.createElement('dd');
      const note = document.createElement('dd');
      tile.title = help;
      term.textContent = name;
      value.className = 'value';
      value.textContent = '—';
      note.className = 'caption';
      note.textContent = typeof caption === 'function' ? 'since the start' : caption;
      tile.append(term, value, note);
      list.append(tile);
      values[key] = value;
      notes[key] = note;
      tiles[key] = tile;
    }
    section.append(heading, list);
    counters.append(section);
  }

  // The strip under the map: one button per key indicator.
  const keys = {};
  for (const [key, page] of KEY_INDICATORS) {
    const item = INDICATOR_GROUPS.flatMap((group) => group.items).find(([id]) => id === key);
    const tile = document.createElement('button');
    tile.type = 'button';
    tile.title = `${item[3]} · click for more`;
    const name = document.createElement('span');
    name.className = 'name';
    name.textContent = item[1];
    const value = document.createElement('span');
    value.className = 'value';
    value.textContent = '—';
    tile.append(name, value);
    tile.addEventListener('click', () => onOpen(page));
    strip.append(tile);
    keys[key] = { tile, value };
  }

  let running = false;
  let run = null;           // run of the newest snapshot
  let resetFromRun = null;  // run being reset, until a snapshot of the new one arrives
  function showToggle(state) {
    running = state.running;
    label.textContent = state.label;
    button.dataset.running = String(state.running);
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
      connection.textContent = connected ? 'Live' : 'Reconnecting…';
      connection.dataset.state = connected ? 'connected' : 'disconnected';
      // A reset sent on a lost connection may never be applied.
      if (!connected) resetFromRun = null;
    },
    setSnapshot(snapshot) {
      if (snapshot.run !== resetFromRun) resetFromRun = null;
      run = snapshot.run;
      showToggle(toggleState(snapshot, resetFromRun));
      time.textContent = formatTime(snapshot.time_s);
      tick.textContent = `tick ${snapshot.tick}`;
      for (const speed of speeds) {
        speed.setAttribute('aria-pressed', String(Number(speed.dataset.speed) === snapshot.speed));
      }
      for (const { key, value, caption, alert } of indicators(snapshot.stats)) {
        values[key].textContent = value;
        notes[key].textContent = caption;
        if (alert) tiles[key].dataset.alert = alert;
        else delete tiles[key].dataset.alert;
        if (!keys[key]) continue;
        keys[key].value.textContent = value;
        if (alert) keys[key].tile.dataset.alert = alert;
        else delete keys[key].tile.dataset.alert;
      }
    },
  };
}
