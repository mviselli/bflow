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
  app.canvas.setAttribute('aria-label', 'Baggage belt from the input to the output');
  // No animation yet: the scene is redrawn only when a snapshot arrives.
  app.stop();
  status.textContent = 'Connecting to the simulation server…';

  const renderer = createRenderer(app);
  let link = null;
  const controls = createControls({ onCommand: (command) => link.send(command) });

  link = connect({
    onConnectionChange(connected) {
      controls.setConnected(connected);
      status.textContent = connected ? '' : 'Waiting for the simulation server…';
    },
    onMessage(message) {
      if (message.type === 'layout') renderer.setLayout(message);
      else if (message.type === 'snapshot') {
        renderer.setSnapshot(message);
        controls.setSnapshot(message);
      } else if (message.type === 'error') console.warn(message.message);
    },
  });
}

initialize().catch((error) => {
  status.textContent = 'Unable to initialize graphics. Check that WebGL is enabled in your browser.';
  console.error('PixiJS initialization failed:', error);
});
