import { Application } from 'pixi.js';
import { connect } from './connection.js';
import { createAlarmList } from './alarms.js';
import { createCharts } from './charts.js';
import { createControls } from './controls.js';
import { createDock } from './dock.js';
import { createEventLog } from './eventlog.js';
import { createHall } from './hall.js';
import { destinationLooks } from './looks.js';
import { createPanel, panelContent } from './panel.js';
import { createPlantControls } from './plantcontrols.js';
import { createRenderer } from './renderer.js';
import './styles.css';

const map = document.querySelector('#map');
const status = document.querySelector('#status');
const indicatorsNote = document.querySelector('#indicators-note');
const app = new Application();
const CANVAS_LABELS = {
  map: 'Baggage plant from the check-in desks to the outputs, seen from above',
  hall: 'Baggage hall seen from one of its corners',
};

// The view shown over the map area, remembered in this browser only
// (storage can be unavailable: then the page starts on the map).
const VIEW_KEY = 'baggageflow.view';
function loadView() {
  try {
    return localStorage.getItem(VIEW_KEY) === 'hall' ? 'hall' : 'map';
  } catch {
    return 'map';
  }
}
function saveView(view) {
  try {
    localStorage.setItem(VIEW_KEY, view);
  } catch {
    // Storage unavailable: the view is simply not remembered.
  }
}

// The legend's destinations: each output's tag code and colour, as on the bags.
function showDestinations(layout, destinations) {
  const list = document.querySelector('#legend-destinations');
  list.replaceChildren(...layout.outputs.map((output) => {
    const look = destinations.get(output.id);
    const item = document.createElement('li');
    const code = document.createElement('span');
    code.className = 'destination-code';
    code.textContent = look.code;
    code.style.background = look.colour;
    const label = document.createElement('span');
    label.textContent = `Exit ${output.label}`;
    item.append(code, label);
    return item;
  }));
}

async function initialize() {
  await app.init({
    resizeTo: map,
    background: '#1f2326',
    antialias: true,
    autoDensity: true,
    resolution: Math.min(window.devicePixelRatio || 1, 2),
  });
  map.appendChild(app.canvas);
  app.canvas.setAttribute('role', 'img');
  status.textContent = 'Connecting to the simulation server…';
  // PixiJS follows only window resizes: the map also changes size when the
  // side panel opens or closes, so follow the element itself.
  new ResizeObserver(() => app.resize()).observe(map);

  let layout = null;
  let destinations = new Map();
  let latest = null;     // the newest snapshot
  let selected = null;
  let link = null;
  const send = (command) => link.send(command);
  const dock = createDock(document.querySelector('.app'));
  const panel = createPanel(document.querySelector('#panel'), { onCommand: send });
  const showPanel = () => panel.show(panelContent(selected, layout, latest, destinations));
  showPanel();
  // A click on the map opens the Details page; a selection made from a list
  // (alarms, belts) shows the element on the map and leaves that list open.
  let fromList = false;
  const onSelect = (selection) => {
    selected = selection;
    showPanel();
    if (selection && !fromList) dock.open('inspect');
  };
  // Two views of the same plant on one canvas: the top-down map and the
  // hall seen from a corner. Both follow every message; only the one shown
  // draws and answers the pointer.
  const renderer = createRenderer(app, { onSelect });
  const hall = createHall(app, { onSelect });
  let view = loadView();
  let switching = false;  // while the hall lies back down into the map
  const shown = () => (view === 'hall' ? hall : renderer);
  const selectFromList = (selection) => {
    fromList = true;
    shown().select(selection);
    fromList = false;
  };
  const viewButtons = [...document.querySelectorAll('.view-switch button')];
  function markView() {
    map.dataset.view = view;
    app.canvas.setAttribute('aria-label', CANVAS_LABELS[view]);
    for (const button of viewButtons) button.setAttribute('aria-pressed', String(button.dataset.view === view));
  }
  // Switching tilts the map up into the hall, or lays the hall back down
  // into the map, keeping the selection; a hidden tab switches at once.
  function showView(next) {
    if (next === view || switching) return;
    const animate = document.visibilityState === 'visible';
    view = next;
    saveView(view);
    markView();
    if (view === 'hall') {
      renderer.setActive(false);
      hall.setActive(true);
      selectFromList(selected);
      hall.enter(animate);
      return;
    }
    switching = true;
    hall.leave(animate, () => {
      hall.setActive(false);
      renderer.setActive(true);
      selectFromList(selected);
      switching = false;
    });
  }
  renderer.setActive(view === 'map');
  hall.setActive(view === 'hall');
  if (view === 'hall') hall.enter(false);
  markView();
  for (const button of viewButtons) button.addEventListener('click', () => showView(button.dataset.view));
  document.querySelector('#zoom-in').addEventListener('click', () => shown().zoomIn());
  document.querySelector('#zoom-out').addEventListener('click', () => shown().zoomOut());
  document.querySelector('#fit').addEventListener('click', () => shown().fit());
  document.querySelector('#turn-left').addEventListener('click', () => hall.turn(-1));
  document.querySelector('#turn-right').addEventListener('click', () => hall.turn(1));
  window.addEventListener('keydown', (event) => {
    if (event.key === 'Escape') shown().clearSelection();
    // Q and E turn the hall, unless the keys are typed into a field.
    const typing = event.target.closest?.('input, textarea, select');
    if (view !== 'hall' || typing || event.ctrlKey || event.metaKey || event.altKey) return;
    if (event.key === 'q' || event.key === 'Q') hall.turn(-1);
    if (event.key === 'e' || event.key === 'E') hall.turn(1);
  });
  let plantControls = null;
  const controls = createControls({
    onCommand: send,
    onOpen: (page) => dock.open(page),
    // The top bar's scenario name opens the list of scenarios.
    onScenario() {
      dock.open('operate');
      plantControls.showView('scenario');
    },
  });
  const eventLog = createEventLog(document.querySelector('.page.events'));
  const charts = createCharts(document.querySelector('#charts'));
  // The Indicators page's two views: counters and charts.
  const statsPage = document.querySelector('.page.stats');
  const statsTabs = [...statsPage.querySelectorAll('.tabs button')];
  for (const tab of statsTabs) {
    tab.addEventListener('click', () => {
      for (const other of statsTabs) other.setAttribute('aria-pressed', String(other === tab));
      for (const view of statsPage.querySelectorAll('.view')) view.hidden = view.dataset.view !== tab.dataset.view;
    });
  }
  const badge = document.querySelector('#alarms-badge');
  const alarmList = createAlarmList(document.querySelector('.page.alarms'), {
    onCommand: send,
    onSelect: selectFromList,
    badge(shown) {
      badge.hidden = shown === null;
      badge.textContent = shown ? String(shown.count) : '';
      badge.dataset.severity = shown?.severity ?? '';
    },
  });
  plantControls = createPlantControls(document.querySelector('.page.operate'), {
    onCommand: send,
    onSelect: selectFromList,
    onStartOver: (scenarioId) => controls.startOver(scenarioId),
  });

  link = connect({
    onConnectionChange(connected) {
      controls.setConnected(connected);
      panel.setConnected(connected);
      alarmList.setConnected(connected);
      plantControls.setConnected(connected);
      // Until the next connection, what is on screen is the last state received.
      const lost = !connected && latest !== null;
      document.body.dataset.connection = connected ? 'connected' : 'disconnected';
      status.textContent = connected ? ''
        : lost ? 'Connection lost · showing the last state received · reconnecting…'
          : 'Waiting for the simulation server…';
      indicatorsNote.textContent = lost ? 'Last values received before the connection was lost' : '';
    },
    onMessage(message) {
      if (message.type === 'layout') {
        layout = message;
        destinations = destinationLooks(layout.outputs);
        latest = null;
        renderer.setLayout(message);
        hall.setLayout(message);
        controls.setLayout(message);
        eventLog.setLayout(message);
        plantControls.setLayout(message);
        showDestinations(layout, destinations);
      }
      else if (message.type === 'snapshot') {
        renderer.setSnapshot(message);
        hall.setSnapshot(message);
        controls.setSnapshot(message);
        eventLog.setSnapshot(message);
        charts.setSnapshot(message);
        alarmList.setSnapshot(message, layout);
        plantControls.setSnapshot(message);
        latest = message;
        showPanel();
      } else if (message.type === 'error') console.warn(message.message);
    },
  });
  // Timers of a hidden tab can be slowed down a lot: check the link as soon
  // as the page is visible again. The picture then jumps to the newest state
  // (see playback.js) instead of replaying what was missed.
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'visible') link.checkStale();
  });
}

initialize().catch((error) => {
  status.textContent = 'Unable to initialize graphics. Check that WebGL is enabled in your browser.';
  console.error('PixiJS initialization failed:', error);
});
