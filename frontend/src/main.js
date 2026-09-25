import { Application, Graphics } from 'pixi.js';
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
  app.canvas.setAttribute('aria-label', 'Initial graphics area, no plant yet');

  const grid = new Graphics();
  app.stage.addChild(grid);

  function drawGrid(width, height) {
    grid.clear();
    for (let x = 0; x < width; x += 40) grid.moveTo(x, 0).lineTo(x, height);
    for (let y = 0; y < height; y += 40) grid.moveTo(0, y).lineTo(width, y);
    grid.stroke({ color: 0x304354, width: 1 });
    app.render();
  }

  app.renderer.on('resize', drawGrid);
  drawGrid(app.screen.width, app.screen.height);
  // The scene is static: the ticker will be started once there are animations.
  app.stop();
  status.textContent = 'Graphics ready · simulation not implemented yet';
}

initialize().catch((error) => {
  status.textContent = 'Unable to initialize graphics. Check that WebGL is enabled in your browser.';
  console.error('PixiJS initialization failed:', error);
});
