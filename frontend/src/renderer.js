// Draws the route with PixiJS from the server's layout and snapshots.
//
// Layers, bottom to top: the floor (tiles, desk, chute, signs, shadows), the
// belt surface, the belt frame (rails and drums) and the bags. The textures
// come from assets.js and are rebuilt when the layout or the screen size
// changes. Every position goes through geometry.js; the renderer never
// invents movement, it places the bags where the latest snapshot says.

import { Container, Sprite, TilingSprite } from 'pixi.js';
import {
  BAG_PADDING_M, BELT, beltSurfaceCanvas, floorCanvas, frameCanvas, suitcaseCanvas, toTexture,
} from './assets.js';
import { BAGGAGE_WIDTH_M, baggageRect, beltGeometry } from './geometry.js';
import { hashString, shortCode, suitcaseLook } from './looks.js';

export function createRenderer(app) {
  const floor = new Sprite();
  const surface = new TilingSprite();
  const frame = new Sprite();
  const bagLayer = new Container();
  app.stage.addChild(floor, surface, frame, bagLayer);

  let layout = null;
  let snapshot = null;
  let geometry = null;
  let resolution = 1;
  let sceneTextures = [];
  const bagSprites = new Map();   // bag id → sprite on screen
  const bagTextures = new Map();  // look → texture shared by bags that look alike

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

    resolution = app.renderer.resolution;
    const { width, height } = app.screen;
    const lengthM = layout.conveyors[0].length_m;
    geometry = beltGeometry(lengthM, width, height);
    const common = { geometry, screenWidth: width, screenHeight: height, resolution, lengthM };

    floor.texture = sceneTexture(floorCanvas({
      ...common, inputCode: shortCode(layout.input_id), outputCode: shortCode(layout.output_id),
    }));
    frame.texture = sceneTexture(frameCanvas(common));
    // Textures are drawn at device resolution; scaling by 1/resolution gives CSS pixels.
    floor.scale.set(1 / resolution);
    frame.scale.set(1 / resolution);

    surface.texture = sceneTexture(beltSurfaceCanvas(geometry.pixelsPerMetre * resolution));
    surface.tileScale.set(1 / resolution);
    surface.position.set(geometry.startX, geometry.centreY - geometry.toPixels(BELT.surfaceM) / 2);
    surface.width = geometry.toPixels(lengthM);
    surface.height = geometry.toPixels(BELT.surfaceM);

    for (const texture of old) texture.destroy(true);
  }

  function bagTexture(baggage) {
    const look = suitcaseLook(baggage);
    const key = `${look.style}|${look.colour}|${look.label}|${baggage.length_m}`;
    if (!bagTextures.has(key)) {
      bagTextures.set(key, toTexture(suitcaseCanvas({
        ...look,
        lengthM: baggage.length_m,
        widthM: BAGGAGE_WIDTH_M,
        scale: geometry.pixelsPerMetre * resolution,
        seed: hashString(key),
      })));
    }
    return bagTextures.get(key);
  }

  function placeBaggage() {
    const present = new Set();
    const padding = geometry.toPixels(BAG_PADDING_M);
    for (const baggage of snapshot ? snapshot.baggage : []) {
      present.add(baggage.id);
      let sprite = bagSprites.get(baggage.id);
      if (!sprite) {
        sprite = new Sprite(bagTexture(baggage));
        sprite.scale.set(1 / resolution);
        bagSprites.set(baggage.id, sprite);
        bagLayer.addChild(sprite);
      }
      // The texture has room for the shadow around the bag itself.
      const rect = baggageRect(geometry, baggage);
      sprite.position.set(rect.x - padding, rect.y - padding);
    }
    for (const [id, sprite] of bagSprites) {
      if (!present.has(id)) {
        sprite.destroy();
        bagSprites.delete(id);
      }
    }
  }

  function draw() {
    if (!layout) return;
    if (!geometry) buildScene();
    placeBaggage();
    app.render();
  }

  // Resizing fires many events: rebuild the textures at most once per frame.
  let resizePending = false;
  app.renderer.on('resize', () => {
    if (resizePending) return;
    resizePending = true;
    requestAnimationFrame(() => {
      resizePending = false;
      geometry = null;
      draw();
    });
  });

  return {
    // A new layout arrives on every (re)connection: forget the old state.
    setLayout(newLayout) {
      layout = newLayout;
      snapshot = null;
      geometry = null;
      draw();
    },
    setSnapshot(newSnapshot) {
      snapshot = newSnapshot;
      draw();
    },
  };
}
