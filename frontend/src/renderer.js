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

import { Container, Sprite, TilingSprite } from 'pixi.js';
import {
  BELT, beltSurfaceCanvas, floorCanvas, frameCanvas, suitcaseCanvas, surfaceSpan, toTexture,
} from './assets.js';
import {
  BAGGAGE_WIDTH_M, baggagePlacement, beltAngle, beltEnds, plantGeometry, pointAlong,
} from './geometry.js';
import { destinationLooks, hashString, shortCode, suitcaseLook } from './looks.js';
import { beltOffset, createPlayback } from './playback.js';

// Real time in seconds, for the display clock.
function nowSeconds() {
  return performance.now() / 1000;
}

export function createRenderer(app) {
  const floor = new Sprite();
  const surfaceLayer = new Container();
  const frame = new Sprite();
  const bagLayer = new Container();
  app.stage.addChild(floor, surfaceLayer, frame, bagLayer);

  let layout = null;
  let belts = new Map();          // belt id → belt from the layout
  let destinations = new Map();   // output id → { code, colour }
  const playback = createPlayback();
  let geometry = null;
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
    geometry = plantGeometry(layout, width, height);
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
    for (const baggage of playback.baggageAt(timeS, belts)) {
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

  // Called by the PixiJS ticker before each frame is rendered.
  function update() {
    if (!layout) return;
    if (!geometry) buildScene();
    const timeS = playback.advance(nowSeconds());
    if (timeS === null) return;
    moveSurfaces(timeS);
    placeBaggage(timeS);
  }
  app.ticker.add(update);

  // Resizing fires many events: rebuild the textures once, on the next frame.
  app.renderer.on('resize', () => {
    geometry = null;
  });

  return {
    // A new layout arrives on every (re)connection: forget the old state.
    setLayout(newLayout) {
      layout = newLayout;
      belts = new Map(layout.belts.map((belt) => [belt.id, belt]));
      destinations = destinationLooks(layout.outputs);
      playback.reset();
      geometry = null;
    },
    setSnapshot(snapshot) {
      playback.add(snapshot, nowSeconds());
    },
  };
}
