import { Application } from 'pixi.js';
import { connect } from './connection.js';
import { createAlarmList } from './alarms.js';
import { createControls } from './controls.js';
import { createDock } from './dock.js';
import { createEventLog } from './eventlog.js';
import { destinationLooks } from './looks.js';
import { createPanel, panelContent } from './panel.js';
import { createPlantControls } from './plantcontrols.js';
import { createRenderer } from './renderer.js';
import './styles.css';

const map = document.querySelector('#map');
const status = document.querySelector('#status');
const indicatorsNote = document.querySelector('#indicators-note');
const app = new Application();

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
  app.canvas.setAttribute('aria-label', 'Baggage plant from the check-in desks to the outputs');
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
  const renderer = createRenderer(app, {
    onSelect(selection) {
      selected = selection;
      showPanel();
      if (selection && !fromList) dock.open('inspect');
    },
  });
  const selectFromList = (selection) => {
    fromList = true;
    renderer.select(selection);
    fromList = false;
  };
  document.querySelector('#zoom-in').addEventListener('click', () => renderer.zoomIn());
  document.querySelector('#zoom-out').addEventListener('click', () => renderer.zoomOut());
  document.querySelector('#fit').addEventListener('click', () => renderer.fit());
  window.addEventListener('keydown', (event) => {
    if (event.key === 'Escape') renderer.clearSelection();
  });
  const controls = createControls({ onCommand: send, onOpen: (page) => dock.open(page) });
  const eventLog = createEventLog(document.querySelector('.page.events'));
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
  const plantControls = createPlantControls(document.querySelector('.page.operate'), {
    onCommand: send,
    onSelect: selectFromList,
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
        eventLog.setLayout(message);
        plantControls.setLayout(message);
        showDestinations(layout, destinations);
      }
      else if (message.type === 'snapshot') {
        renderer.setSnapshot(message);
        controls.setSnapshot(message);
        eventLog.setSnapshot(message);
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
