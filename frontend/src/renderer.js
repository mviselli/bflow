// Draws the plant with PixiJS from the server's layout and snapshots.
//
// Layers, bottom to top: the floor (tiles, direction arrows, desks, chutes,
// signs, shadows), the belt surfaces, the belt frames (rails, drums and the
// transfer plates where belts meet) and the bags. The textures come from
// assets.js and are rebuilt when the layout or the screen size changes.
// Every position goes through geometry.js.
//
// The scene is redrawn on every screen frame. Snapshots go to playback.js,
// which gives the simulated time to draw and the bags between the two
// snapshots around it: the renderer never invents movement, and when the
// simulation is paused the bags and the belt surfaces stop with it.
//
// Zoom and panning move a camera (geometry.js). All layers sit in one
// `world` container: while the view changes the container is scaled and
// moved at once, and when it has been still for REBUILD_DELAY_MS the
// textures are redrawn sharp for the new view. Clicking a bag or a belt
// selects it: an outline follows it and onSelect reports it.

import { Container, Graphics, Sprite, TilingSprite } from 'pixi.js';
import {
  BELT, beltSurfaceCanvas, floorCanvas, frameCanvas, suitcaseCanvas, surfaceSpan, toTexture,
} from './assets.js';
import {
  BAGGAGE_WIDTH_M, BELT_WIDTH_M, FIT_CAMERA, baggagePlacement, beltAngle, beltEnds, clampCamera, panBy,
  pickAt, plantGeometry, pointAlong, zoomAround,
} from './geometry.js';
import { destinationLooks, hashString, shortCode, suitcaseLook } from './looks.js';
import { beltOffset, createPlayback } from './playback.js';

// Real time in seconds, for the display clock.
function nowSeconds() {
  return performance.now() / 1000;
}

// Redraw the textures once the view has been still for this long.
const REBUILD_DELAY_MS = 150;
// A press that moves less than this is a click, not a drag (pixels).
const CLICK_SLOP_PX = 4;
// Extra reach around bags and belts when picking, in screen pixels.
const PICK_TOLERANCE_PX = 6;
const SELECTION_COLOUR = 0xf2c230;

// Outline of a rectangle along a belt: from `from` to `to` metres along it,
// `widthM` wide, in screen pixels of `geometry`.
function outlineAlong(graphics, geometry, belt, from, to, widthM) {
  const angle = beltAngle(belt);
  const across = { x: -Math.sin(angle) * widthM / 2, y: Math.cos(angle) * widthM / 2 };
  const corners = [
    [pointAlong(belt, from), 1], [pointAlong(belt, to), 1],
    [pointAlong(belt, to), -1], [pointAlong(belt, from), -1],
  ].map(([point, side]) => geometry.toScreen({
    x_m: point.x_m + side * across.x, y_m: point.y_m + side * across.y,
  }));
  graphics.poly(corners.flatMap(({ x, y }) => [x, y]))
    .stroke({ width: 2, color: SELECTION_COLOUR, alignment: 1 });
}

export function createRenderer(app, { onSelect = () => {} } = {}) {
  const world = new Container();
  const floor = new Sprite();
  const surfaceLayer = new Container();
  const frame = new Sprite();
  const highlight = new Graphics();
  const bagLayer = new Container();
  world.addChild(floor, surfaceLayer, frame, highlight, bagLayer);
  app.stage.addChild(world);

  let layout = null;
  let belts = new Map();          // belt id → belt from the layout
  let destinations = new Map();   // output id → { code, colour }
  const playback = createPlayback();
  let geometry = null;            // the view the textures were drawn for
  let camera = FIT_CAMERA;        // the view to show
  let rebuildTimer = null;
  let drawnBags = [];             // bags of the last frame, as drawn
  let selection = null;           // { kind: 'bag' | 'belt', id } or null
  let resolution = 1;
  let sceneTextures = [];
  const surfaces = new Map();     // belt id → TilingSprite of its moving surface
  const bagSprites = new Map();   // bag id → sprite on screen
  const bagTextures = new Map();  // look and angle → texture shared by bags that look alike

  function sceneTexture(canvas) {
    const texture = toTexture(canvas);
    sceneTextures.push(texture);
    return texture;
  }

  function clearBags() {
    for (const sprite of bagSprites.values()) sprite.destroy();
    bagSprites.clear();
    for (const texture of bagTextures.values()) texture.destroy(true);
    bagTextures.clear();
  }

  // Redraws every texture for the current layout and screen size.
  function buildScene() {
    const old = sceneTextures;
    sceneTextures = [];
    clearBags();
    for (const surface of surfaces.values()) surface.destroy();
    surfaces.clear();

    resolution = app.renderer.resolution;
    const { width, height } = app.screen;
    // A resize can leave the old centre out of range.
    if (camera.centre) camera = clampCamera(layout, camera, width, height);
    geometry = plantGeometry(layout, width, height, camera);
    world.position.set(0, 0);
    world.scale.set(1);
    const common = { geometry, layout, screenWidth: width, screenHeight: height, resolution };
    const inputCodes = new Map(layout.inputs.map((input) => [input.id, shortCode(input.id)]));

    floor.texture = sceneTexture(floorCanvas({ ...common, inputCodes, destinations }));
    frame.texture = sceneTexture(frameCanvas(common));
    // Textures are drawn at device resolution; scaling by 1/resolution gives CSS pixels.
    floor.scale.set(1 / resolution);
    frame.scale.set(1 / resolution);

    // One moving surface per belt, all sharing the same slat texture.
    const slat = sceneTexture(beltSurfaceCanvas(geometry.pixelsPerMetre * resolution));
    const ends = beltEnds(layout);
    for (const belt of layout.belts) {
      const { from, to } = surfaceSpan(belt, ends.get(belt.id));
      const surface = new TilingSprite({ texture: slat });
      surface.tileScale.set(1 / resolution);
      surface.anchor.set(0, 0.5);
      const start = geometry.toScreen(pointAlong(belt, from));
      surface.position.set(start.x, start.y);
      surface.rotation = beltAngle(belt);
      surface.width = geometry.toPixels(to - from);
      surface.height = geometry.toPixels(BELT.surfaceM);
      surfaceLayer.addChild(surface);
      surfaces.set(belt.id, surface);
    }

    for (const texture of old) texture.destroy(true);
  }

  function bagTexture(baggage, angle) {
    const look = suitcaseLook(baggage, destinations);
    const key = `${look.style}|${look.colour}|${look.label}|${baggage.length_m}|${angle.toFixed(3)}`;
    if (!bagTextures.has(key)) {
      bagTextures.set(key, toTexture(suitcaseCanvas({
        ...look,
        lengthM: baggage.length_m,
        widthM: BAGGAGE_WIDTH_M,
        angle,
        scale: geometry.pixelsPerMetre * resolution,
        seed: hashString(key),
      })));
    }
    return bagTextures.get(key);
  }

  // Scrolls each rubber surface by the distance its belt has travelled.
  function moveSurfaces(timeS) {
    for (const belt of layout.belts) {
      const surface = surfaces.get(belt.id);
      const tileWidthM = surface.texture.width / resolution / geometry.pixelsPerMetre;
      surface.tilePosition.x = geometry.toPixels(beltOffset(belt.speed_m_s, timeS, tileWidthM));
    }
  }

  function placeBaggage(timeS) {
    const present = new Set();
    drawnBags = playback.baggageAt(timeS, belts);
    for (const baggage of drawnBags) {
      const belt = belts.get(baggage.conveyor_id);
      if (!belt) continue;
      const place = baggagePlacement(geometry, belt, baggage);
      const texture = bagTexture(baggage, place.angle);
      present.add(baggage.id);
      let sprite = bagSprites.get(baggage.id);
      if (!sprite) {
        sprite = new Sprite(texture);
        sprite.anchor.set(0.5);
        sprite.scale.set(1 / resolution);
        bagSprites.set(baggage.id, sprite);
        bagLayer.addChild(sprite);
      }
      // A bag on a belt with another direction needs the texture for that angle.
      sprite.texture = texture;
      sprite.position.set(place.x, place.y);
      sprite.alpha = baggage.alpha;
    }
    for (const [id, sprite] of bagSprites) {
      if (!present.has(id)) {
        sprite.destroy();
        bagSprites.delete(id);
      }
    }
  }

  // Selects what was picked (or nothing); a bag also reports its destination.
  function select(picked) {
    const same = picked?.kind === selection?.kind && picked?.id === selection?.id;
    if (same) return;
    selection = picked;
    if (selection?.kind === 'bag') {
      const baggage = drawnBags.find((bag) => bag.id === selection.id);
      selection = { ...selection, destination_id: baggage?.destination_id ?? null };
    }
    onSelect(selection);
  }

  // Outline around the selected belt or bag, following the bag as it moves.
  // A selected bag that has left the plant is no longer selected.
  function drawHighlight() {
    highlight.clear();
    if (!selection) return;
    if (selection.kind === 'belt') {
      const belt = belts.get(selection.id);
      if (belt) outlineAlong(highlight, geometry, belt, 0, belt.length_m, BELT_WIDTH_M + 0.1);
      return;
    }
    const baggage = drawnBags.find((bag) => bag.id === selection.id);
    const belt = baggage && belts.get(baggage.conveyor_id);
    if (!belt) {
      select(null);
      return;
    }
    outlineAlong(highlight, geometry, belt, baggage.position_m - 0.08,
      baggage.position_m + baggage.length_m + 0.08, BAGGAGE_WIDTH_M + 0.16);
  }

  // Called by the PixiJS ticker before each frame is rendered.
  function update() {
    if (!layout) return;
    if (!geometry) buildScene();
    const timeS = playback.advance(nowSeconds());
    if (timeS === null) return;
    moveSurfaces(timeS);
    placeBaggage(timeS);
    drawHighlight();
  }
  app.ticker.add(update);

  // Shows the camera at once by moving the world container over the
  // textures already drawn, then redraws them once the view stays still.
  function setCamera(next) {
    camera = next;
    if (!geometry) return;
    const { width, height } = app.screen;
    const view = plantGeometry(layout, width, height, camera);
    const scale = view.pixelsPerMetre / geometry.pixelsPerMetre;
    world.scale.set(scale);
    world.position.set(view.originX - geometry.originX * scale, view.originY - geometry.originY * scale);
    clearTimeout(rebuildTimer);
    rebuildTimer = setTimeout(() => {
      geometry = null;
    }, REBUILD_DELAY_MS);
  }

  // Screen point of a pointer event, in the canvas's CSS pixels.
  function pointerPoint(event) {
    const box = app.canvas.getBoundingClientRect();
    return { x: event.clientX - box.left, y: event.clientY - box.top };
  }

  // What is under a screen point, in the view currently shown.
  function pickScreen(point) {
    const { width, height } = app.screen;
    const view = plantGeometry(layout, width, height, camera);
    return pickAt(view.toMap(point), drawnBags, belts, PICK_TOLERANCE_PX / view.pixelsPerMetre);
  }

  // Mouse wheel zooms around the pointer; dragging pans; a click selects.
  const canvas = app.canvas;
  let press = null;  // { id, start, last, dragging } while a pointer is down
  canvas.addEventListener('wheel', (event) => {
    if (!layout) return;
    event.preventDefault();
    const { width, height } = app.screen;
    const factor = Math.exp(-event.deltaY * (event.deltaMode === 1 ? 0.05 : 0.0015));
    setCamera(zoomAround(layout, camera, width, height, pointerPoint(event), factor));
  }, { passive: false });
  canvas.addEventListener('pointerdown', (event) => {
    if (!layout || event.button !== 0) return;
    const point = pointerPoint(event);
    press = { id: event.pointerId, start: point, last: point, dragging: false };
    canvas.setPointerCapture(event.pointerId);
  });
  canvas.addEventListener('pointermove', (event) => {
    if (!layout) return;
    const point = pointerPoint(event);
    if (!press || press.id !== event.pointerId) {
      canvas.style.cursor = pickScreen(point) ? 'pointer' : camera.zoom > 1 ? 'grab' : '';
      return;
    }
    const moved = Math.hypot(point.x - press.start.x, point.y - press.start.y);
    if (!press.dragging && moved < CLICK_SLOP_PX) return;
    press.dragging = true;
    canvas.style.cursor = 'grabbing';
    const { width, height } = app.screen;
    setCamera(panBy(layout, camera, width, height, point.x - press.last.x, point.y - press.last.y));
    press.last = point;
  });
  canvas.addEventListener('pointerup', (event) => {
    if (!press || press.id !== event.pointerId) return;
    if (!press.dragging) select(pickScreen(pointerPoint(event)));
    press = null;
    canvas.style.cursor = '';
  });
  canvas.addEventListener('pointercancel', () => {
    press = null;
  });

  // Resizing fires many events: rebuild the textures once, on the next frame.
  app.renderer.on('resize', () => {
    geometry = null;
  });

  function zoomBy(factor) {
    if (!layout) return;
    const { width, height } = app.screen;
    setCamera(zoomAround(layout, camera, width, height, { x: width / 2, y: height / 2 }, factor));
  }

  return {
    // A new layout arrives on every (re)connection: forget the old state.
    setLayout(newLayout) {
      layout = newLayout;
      belts = new Map(layout.belts.map((belt) => [belt.id, belt]));
      destinations = destinationLooks(layout.outputs);
      playback.reset();
      camera = FIT_CAMERA;
      geometry = null;
      drawnBags = [];
      select(null);
    },
    zoomIn: () => zoomBy(1.5),
    zoomOut: () => zoomBy(1 / 1.5),
    // Back to the whole plant.
    fit: () => layout && setCamera(FIT_CAMERA),
    clearSelection: () => select(null),
    setSnapshot(snapshot) {
      playback.add(snapshot, nowSeconds());
    },
  };
}
