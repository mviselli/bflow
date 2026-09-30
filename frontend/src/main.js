import { Application } from 'pixi.js';
import { connect } from './connection.js';
import { createControls } from './controls.js';
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
  const selection = document.querySelector('#selection');
  const hint = 'Click a bag or a belt to select it. Scroll to zoom, drag to move the view.';
  selection.textContent = hint;
  const renderer = createRenderer(app, {
    onSelect(selected) {
      selection.textContent = selected ? describeSelection(selected, layout) : hint;
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
        renderer.setLayout(message);
      }
      else if (message.type === 'snapshot') {
        renderer.setSnapshot(message);
        controls.setSnapshot(message);
      } else if (message.type === 'error') console.warn(message.message);
    },
  });
}

// One line about the selected bag or belt; the side panel will show more.
function describeSelection(selected, layout) {
  if (selected.kind === 'belt') return `Selected belt ${selected.id} · Esc to clear`;
  const output = layout?.outputs.find((node) => node.id === selected.destination_id);
  const destination = output ? ` going to ${output.label}` : '';
  return `Selected bag ${selected.id}${destination} · Esc to clear`;
}

initialize().catch((error) => {
  status.textContent = 'Unable to initialize graphics. Check that WebGL is enabled in your browser.';
  console.error('PixiJS initialization failed:', error);
});
