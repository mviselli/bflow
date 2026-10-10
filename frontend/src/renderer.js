// Draws the plant with PixiJS from the server's layout and snapshots.
//
// Layers, bottom to top: the floor (tiles, direction arrows, desks and their
// queue lanes, chutes, signs, shadows), the belt surfaces, the belt frames
// (rails, drums and the transfer plates where belts meet), the passengers
// queueing at the desks (passengers.js decides where) and the bags. The textures come from
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
// textures are redrawn sharp for the new view. Clicking a bag, a check-in
// desk or a belt selects it: an outline follows it and onSelect reports it.
// A halted belt (stopped by the operator or faulty) keeps its surface still.
//
// Signals sit over the frames (signals.js decides what they show): a status
// light beside each belt, with its own symbol and colour — a small grey dot
// running, a blue square stopped by the operator, an amber triangle for a
// warning, a red circle with a cross faulty — blinking while an alarm of the
// belt is not acknowledged, and a red pulse over an output's chute when a
// bag arrives there by mistake.
//
// A resize (the window, or the side panel opening or closing) is shown like
// a camera move: the textures already drawn are scaled at once and redrawn
// sharp once the size stays still, so the map follows the panel smoothly.

import { Container, Graphics, Sprite, Text, TilingSprite } from 'pixi.js';
import {
  BELT, CANVAS_FONT, PASSENGER_ANCHOR, beltSurfaceCanvas, floorCanvas, frameCanvas, passengerCanvas,
  suitcaseCanvas, surfaceSpan, toTexture,
} from './assets.js';
import {
  BAGGAGE_WIDTH_M, BELT_WIDTH_M, DESK_SPAN, FIT_CAMERA, baggagePlacement, beltAngle, beltEnds,
  clampCamera, panBy,
  pickAt, plantGeometry, pointAlong, samePlant, zoomAround,
} from './geometry.js';
import { destinationLooks, hashString, shortCode, suitcaseLook } from './looks.js';
import {
  LANE, MAX_SHOWN, addQueueSnapshot, deskToMap, passengerLook, passengersAt, queuePoint,
} from './passengers.js';
import { advanceSurface, createPlayback, isNewRun } from './playback.js';
import { addWrongExits, beltLights, wrongExitSignals } from './signals.js';

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
const SELECTION_COLOUR = 0xffffff;
// Status lights: colour by state (as in styles.css), radius and place beside
// the belt (metres).
const LIGHT_COLOURS = { fault: 0xf0524f, warning: 0xf2b33d, stopped: 0x5b9bff, running: 0x8a939a };
const LIGHT_BACKING = 0x15181a;
const LIGHT_RADIUS_M = 0.17;
const LIGHT_ALONG_M = 1.2;
const LIGHT_ASIDE_M = BELT_WIDTH_M / 2 + 0.3;
// A blinking light: on for this share of each period, in real time.
const BLINK_PERIOD_S = 0.8;
const BLINK_ON = 0.6;
const WRONG_EXIT_COLOUR = 0xf0524f;
// Passenger textures are drawn for this many facings, a full turn.
const PASSENGER_FACINGS = 32;

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

// A belt light's symbol, centred on (x, y) and about `radius` in size.
function drawLight(graphics, x, y, radius, state, alpha) {
  const color = LIGHT_COLOURS[state];
  if (state === 'running') {
    graphics.circle(x, y, radius * 0.55).fill({ color, alpha });
  } else if (state === 'stopped') {
    const half = radius * 0.72;
    graphics.rect(x - half, y - half, half * 2, half * 2).fill({ color, alpha });
  } else if (state === 'warning') {
    graphics.poly([x, y - radius * 0.95, x + radius, y + radius * 0.75, x - radius, y + radius * 0.75])
      .fill({ color, alpha });
  } else {
    const arm = radius * 0.42;
    graphics.circle(x, y, radius).fill({ color, alpha });
    graphics.moveTo(x - arm, y - arm).lineTo(x + arm, y + arm)
      .moveTo(x + arm, y - arm).lineTo(x - arm, y + arm)
      .stroke({ width: Math.max(radius * 0.32, 1.5), color: LIGHT_BACKING, alpha, cap: 'round' });
  }
}

export function createRenderer(app, { onSelect = () => {} } = {}) {
  const world = new Container();
  const floor = new Sprite();
  const surfaceLayer = new Container();
  const frame = new Sprite();
  const signals = new Graphics();
  const highlight = new Graphics();
  const people = new Container();
  const bagLayer = new Container();
  world.addChild(floor, surfaceLayer, frame, people, signals, highlight, bagLayer);
  app.stage.addChild(world);

  let layout = null;
  let belts = new Map();          // belt id → belt from the layout
  let destinations = new Map();   // output id → { code, colour }
  const playback = createPlayback();
  let geometry = null;            // the view the textures were drawn for
  let camera = FIT_CAMERA;        // the view to show
  let rebuildTimer = null;
  let drawnBags = [];             // bags of the last frame, as drawn
  let desks = [];                 // { id, belt } for each input and the belt it feeds
  let selection = null;           // { kind: 'bag' | 'input' | 'belt', id } or null
  let haltedBelts = new Set();    // belts stopped or faulty, from the newest snapshot
  let newest = null;              // the newest snapshot
  let lights = new Map();         // belt id → { state, blinking }, from the newest snapshot
  let wrongExits = [];            // recent wrong arrivals, { outputId, timeS }
  let queues = new Map();         // input id → its queue, from the snapshots (passengers.js)
  const surfaceOffsets = new Map(); // belt id → offset of its surface in metres
  let surfaceTime = null;         // simulated time the surfaces were last moved to
  let resolution = 1;
  let sceneTextures = [];
  const surfaces = new Map();     // belt id → TilingSprite of its moving surface
  const bagSprites = new Map();   // bag id → sprite on screen
  const bagTextures = new Map();  // look and angle → texture shared by bags that look alike
  const passengerSprites = new Map();   // "input id#number" → sprite on screen
  const passengerTextures = new Map();  // look and facing → texture
  const queueBadges = new Map();        // input id → "+N" text beyond the last passenger drawn

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
    for (const sprite of passengerSprites.values()) sprite.destroy();
    passengerSprites.clear();
    for (const texture of passengerTextures.values()) texture.destroy(true);
    passengerTextures.clear();
    for (const badge of queueBadges.values()) badge.destroy();
    queueBadges.clear();
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

  // Scrolls each rubber surface by the distance its belt has run since the
  // last frame: nothing while simulated time stands still or the belt is
  // halted. Time going back (a reset) starts every surface again from 0.
  function moveSurfaces(timeS) {
    let dtS = surfaceTime === null ? 0 : timeS - surfaceTime;
    if (dtS < 0) {
      surfaceOffsets.clear();
      dtS = 0;
    }
    surfaceTime = timeS;
    for (const belt of layout.belts) {
      const surface = surfaces.get(belt.id);
      const tileWidthM = surface.texture.width / resolution / geometry.pixelsPerMetre;
      const speed = haltedBelts.has(belt.id) ? 0 : belt.speed_m_s;
      const offset = advanceSurface(surfaceOffsets.get(belt.id) ?? 0, speed, dtS, tileWidthM);
      surfaceOffsets.set(belt.id, offset);
      surface.tilePosition.x = geometry.toPixels(offset);
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

  function passengerTexture(look, angle) {
    const step = (2 * Math.PI) / PASSENGER_FACINGS;
    const facing = ((Math.round(angle / step) % PASSENGER_FACINGS) + PASSENGER_FACINGS) % PASSENGER_FACINGS;
    const key = `${look.coat}|${look.hair}|${look.skin}|${facing}`;
    if (!passengerTextures.has(key)) {
      passengerTextures.set(key, toTexture(passengerCanvas({
        ...look, angle: facing * step, scale: geometry.pixelsPerMetre * resolution,
      })));
    }
    return passengerTextures.get(key);
  }

  // The passengers in each desk's line at the displayed time, and a "+N"
  // badge past the last one when more wait than are drawn.
  function placePassengers(timeS) {
    const present = new Set();
    for (const { id, belt } of desks) {
      const queue = queues.get(id);
      if (!queue || !belt) continue;
      const input = layout.inputs.find((node) => node.id === id);
      const angle = beltAngle(belt);
      const { passengers, extra } = passengersAt(queue, timeS);
      for (const { number, slot, alpha } of passengers) {
        const key = `${id}#${number}`;
        const point = queuePoint(slot);
        const screen = geometry.toScreen(deskToMap(input.position, angle, point));
        let sprite = passengerSprites.get(key);
        if (!sprite) {
          sprite = new Sprite();
          sprite.anchor.set(PASSENGER_ANCHOR.x, PASSENGER_ANCHOR.y);
          sprite.scale.set(1 / resolution);
          passengerSprites.set(key, sprite);
          people.addChild(sprite);
        }
        sprite.texture = passengerTexture(passengerLook(id, number), angle + point.facing);
        sprite.position.set(screen.x, screen.y);
        sprite.alpha = alpha;
        present.add(key);
      }
      let badge = queueBadges.get(id);
      if (extra > 0) {
        if (!badge) {
          badge = new Text({ text: '', style: {
            fontFamily: CANVAS_FONT, fontWeight: '700', fill: 0xe8eef3,
            fontSize: Math.max(geometry.toPixels(0.32), 9),
          } });
          badge.anchor.set(0.5);
          queueBadges.set(id, badge);
          people.addChild(badge);
        }
        const place = { x: LANE.fromM + LANE.pitchM * (MAX_SHOWN - 1) + 0.15, y: LANE.y };
        const screen = geometry.toScreen(deskToMap(input.position, angle, place));
        badge.text = `+${extra}`;
        badge.position.set(screen.x, screen.y);
      } else if (badge) {
        badge.destroy();
        queueBadges.delete(id);
      }
    }
    for (const [key, sprite] of passengerSprites) {
      if (!present.has(key)) {
        sprite.destroy();
        passengerSprites.delete(key);
      }
    }
  }

  // Selects what was picked, or nothing.
  function select(picked) {
    const same = picked?.kind === selection?.kind && picked?.id === selection?.id;
    if (same) return;
    selection = picked;
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
    if (selection.kind === 'input') {
      const desk = desks.find((item) => item.id === selection.id);
      if (desk) outlineAlong(highlight, geometry, desk.belt, DESK_SPAN.fromM, DESK_SPAN.toM, DESK_SPAN.widthM);
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

  // A point `alongM` metres along a belt and `asideM` to the left of it.
  function besideBelt(belt, alongM, asideM) {
    const angle = beltAngle(belt);
    const point = pointAlong(belt, alongM);
    return geometry.toScreen({
      x_m: point.x_m + Math.sin(angle) * asideM, y_m: point.y_m - Math.cos(angle) * asideM,
    });
  }

  // Belt lights (newest snapshot, blinking in real time) and wrong-arrival
  // pulses (displayed simulated time).
  function drawSignals(timeS) {
    signals.clear();
    const lit = (nowSeconds() % BLINK_PERIOD_S) < BLINK_PERIOD_S * BLINK_ON;
    const radius = Math.max(geometry.toPixels(LIGHT_RADIUS_M), 3);
    for (const belt of layout.belts) {
      const light = lights.get(belt.id);
      if (!light) continue;
      const { x, y } = besideBelt(belt, Math.min(LIGHT_ALONG_M, belt.length_m / 2), LIGHT_ASIDE_M);
      const alpha = !light.blinking || lit ? 1 : 0.25;
      signals.circle(x, y, radius * 1.35).fill({ color: LIGHT_BACKING, alpha: 0.85 });
      drawLight(signals, x, y, radius, light.state, alpha);
    }
    for (const [outputId, progress] of wrongExitSignals(wrongExits, timeS)) {
      const output = layout.outputs.find((node) => node.id === outputId);
      const belt = layout.belts.find((item) => item.target_id === outputId);
      if (!output || !belt) continue;
      // Three pulses fading out over the chute, past the end of the belt.
      const alpha = (1 - progress) * (0.55 + 0.45 * Math.cos(2 * Math.PI * 3 * progress));
      const angle = beltAngle(belt);
      const corners = [[0, -0.8], [BELT.drumM + 1.45, -0.8], [BELT.drumM + 1.45, 0.8], [0, 0.8]]
        .map(([along, across]) => geometry.toScreen({
          x_m: output.position.x_m + along * Math.cos(angle) - across * Math.sin(angle),
          y_m: output.position.y_m + along * Math.sin(angle) + across * Math.cos(angle),
        }));
      signals.poly(corners.flatMap(({ x, y }) => [x, y]))
        .fill({ color: WRONG_EXIT_COLOUR, alpha: alpha * 0.35 })
        .stroke({ width: 3, color: WRONG_EXIT_COLOUR, alpha });
    }
  }

  // Called by the PixiJS ticker before each frame is rendered.
  function update() {
    if (!layout) return;
    if (!geometry) buildScene();
    const timeS = playback.advance(nowSeconds());
    if (timeS === null) return;
    moveSurfaces(timeS);
    placePassengers(timeS);
    placeBaggage(timeS);
    drawSignals(timeS);
    drawHighlight();
  }
  app.ticker.add(update);
  // Signs and tags use the interface's typeface: redraw once it has loaded.
  document.fonts?.load(`700 16px ${CANVAS_FONT}`).then(() => {
    geometry = null;
  });

  // Shows the camera at once by moving the world container over the
  // textures already drawn, then redraws them once the view stays still.
  function setCamera(next) {
    camera = next;
    showView();
  }

  // The current camera on the current screen size, over the textures drawn
  // for the last view; a full redraw follows once the view stays still.
  function showView() {
    if (!geometry) return;
    const { width, height } = app.screen;
    // A smaller screen can leave the centre out of range.
    if (camera.centre) camera = clampCamera(layout, camera, width, height);
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
    return pickAt(view.toMap(point), drawnBags, belts, PICK_TOLERANCE_PX / view.pixelsPerMetre, desks);
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

  // Resizing fires many events (one per frame while the side panel slides):
  // follow each one with the textures already drawn, redraw once still.
  app.renderer.on('resize', () => showView());

  function zoomBy(factor) {
    if (!layout) return;
    const { width, height } = app.screen;
    setCamera(zoomAround(layout, camera, width, height, { x: width / 2, y: height / 2 }, factor));
  }

  return {
    // A new layout arrives on every (re)connection, with a full state after
    // it: forget the old state. For the same plant, keep the view and a
    // selected belt or desk; a bag may belong to an old run, so it goes.
    setLayout(newLayout) {
      const keep = samePlant(layout, newLayout);
      layout = newLayout;
      belts = new Map(layout.belts.map((belt) => [belt.id, belt]));
      destinations = destinationLooks(layout.outputs);
      desks = layout.inputs.map((input) => ({
        id: input.id, belt: layout.belts.find((belt) => belt.source_id === input.id),
      }));
      playback.reset();
      surfaceOffsets.clear();
      surfaceTime = null;
      newest = null;
      lights = new Map();
      wrongExits = [];
      queues = new Map();
      if (!keep) camera = FIT_CAMERA;
      geometry = null;
      drawnBags = [];
      if (!keep || selection?.kind === 'bag') select(null);
    },
    zoomIn: () => zoomBy(1.5),
    zoomOut: () => zoomBy(1 / 1.5),
    // Back to the whole plant.
    fit: () => layout && setCamera(FIT_CAMERA),
    clearSelection: () => select(null),
    // Selects a belt, desk or bag from outside the map (the alarm list).
    select: (picked) => select(picked),
    setSnapshot(snapshot) {
      // A new run (a reset): nothing of the old run may stay on screen. Bag
      // ids start again from bag-1, so a selected bag would become another
      // one, and the surfaces start again from 0.
      if (newest && isNewRun(newest, snapshot)) {
        if (selection?.kind === 'bag') select(null);
        surfaceOffsets.clear();
        surfaceTime = null;
        wrongExits = [];
        queues = new Map();
      }
      newest = snapshot;
      queues = addQueueSnapshot(queues, snapshot);
      lights = beltLights(snapshot);
      wrongExits = addWrongExits(wrongExits, snapshot);
      haltedBelts = new Set(snapshot.belts.filter((belt) => belt.stopped || belt.faulty)
        .map((belt) => belt.id));
      playback.add(snapshot, nowSeconds());
    },
  };
}
