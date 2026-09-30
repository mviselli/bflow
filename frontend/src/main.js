import { Application } from 'pixi.js';
import { connect } from './connection.js';
import { createControls } from './controls.js';
import { destinationLooks } from './looks.js';
import { createPanel, panelContent } from './panel.js';
import { createRenderer } from './renderer.js';
import './styles.css';

const map = document.querySelector('#map');
const status = document.querySelector('#status');
const app = new Application();

async function initialize() {
  await app.init({
    resizeTo: map,
    background: '#172635',
    antialias: true,
    autoDensity: true,
    resolution: Math.min(window.devicePixelRatio || 1, 2),
  });
  map.appendChild(app.canvas);
  app.canvas.setAttribute('role', 'img');
  app.canvas.setAttribute('aria-label', 'Baggage plant from the check-in desks to the outputs');
  status.textContent = 'Connecting to the simulation server…';

  let layout = null;
  let destinations = new Map();
  let latest = null;     // the newest snapshot
  let selected = null;
  const panel = createPanel(document.querySelector('#panel'));
  const showPanel = () => panel.show(panelContent(selected, layout, latest, destinations));
  showPanel();
  const renderer = createRenderer(app, {
    onSelect(selection) {
      selected = selection;
      showPanel();
    },
  });
  document.querySelector('#zoom-in').addEventListener('click', () => renderer.zoomIn());
  document.querySelector('#zoom-out').addEventListener('click', () => renderer.zoomOut());
  document.querySelector('#fit').addEventListener('click', () => renderer.fit());
  window.addEventListener('keydown', (event) => {
    if (event.key === 'Escape') renderer.clearSelection();
  });
  let link = null;
  const controls = createControls({ onCommand: (command) => link.send(command) });

  link = connect({
    onConnectionChange(connected) {
      controls.setConnected(connected);
      status.textContent = connected ? '' : 'Waiting for the simulation server…';
    },
    onMessage(message) {
      if (message.type === 'layout') {
        layout = message;
        destinations = destinationLooks(layout.outputs);
        latest = null;
        renderer.setLayout(message);
      }
      else if (message.type === 'snapshot') {
        renderer.setSnapshot(message);
        controls.setSnapshot(message);
        latest = message;
        showPanel();
      } else if (message.type === 'error') console.warn(message.message);
    },
  });
}

initialize().catch((error) => {
  status.textContent = 'Unable to initialize graphics. Check that WebGL is enabled in your browser.';
  console.error('PixiJS initialization failed:', error);
});
