// Procedural graphics assets, drawn with the Canvas 2D API and turned into
// PixiJS textures.
//
// Every asset shares the same art direction so the scene stays coherent:
// - strictly top-down view, sizes in metres (ctx.scale converts to pixels);
// - light from the top-left: highlights on top/left edges, shadows falling
//   down-right, longer for objects that stand higher above the floor;
// - a muted terminal palette with yellow for safety markings and signs.
// The shapes are decoration only: positions and collisions stay in Python.

import { Texture } from 'pixi.js';
import { BELT_WIDTH_M } from './geometry.js';

// Shadow offset in metres per metre of height above the floor.
const LIGHT = { x: 0.35, y: 0.55 };

export const BELT = {
  railM: 0.1,                        // steel rail on each side
  surfaceM: BELT_WIDTH_M - 0.2,      // rubber surface between the rails
  slatM: 0.125,                      // distance between two slats
  drumM: 0.12,                       // end drum beyond each end of the belt
};

export const BAG_PADDING_M = 0.16;   // room around a bag for its shadow

// --- Small helpers ---------------------------------------------------------

// Canvas measured in metres: after ctx.scale, one unit is one metre.
function metreCanvas(widthM, heightM, scale) {
  const canvas = document.createElement('canvas');
  canvas.width = Math.max(1, Math.ceil(widthM * scale));
  canvas.height = Math.max(1, Math.ceil(heightM * scale));
  const ctx = canvas.getContext('2d');
  ctx.scale(scale, scale);
  return { canvas, ctx };
}

export function toTexture(canvas) {
  return Texture.from(canvas, true);
}

// Deterministic pseudo-random numbers: the scene looks the same at every redraw.
function seededRandom(seed) {
  let state = seed >>> 0;
  return () => {
    state = (state + 0x6d2b79f5) >>> 0;
    let t = state;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

// Lighter (amount > 0) or darker (amount < 0) version of a #rrggbb colour.
function shade(hex, amount) {
  const value = parseInt(hex.slice(1), 16);
  const mix = (channel) => Math.round(amount < 0
    ? channel * (1 + amount)
    : channel + (255 - channel) * amount);
  return `rgb(${mix(value >> 16)}, ${mix((value >> 8) & 255)}, ${mix(value & 255)})`;
}

// Soft shadow for whatever is filled next, for an object heightM above the floor.
function castShadow(ctx, scale, heightM, opacity = 0.5) {
  // Shadow sizes are in canvas pixels: ctx.scale does not apply to them.
  ctx.shadowColor = `rgba(0, 0, 0, ${opacity})`;
  ctx.shadowBlur = (0.03 + heightM * 0.25) * scale;
  ctx.shadowOffsetX = LIGHT.x * heightM * scale;
  ctx.shadowOffsetY = LIGHT.y * heightM * scale;
}

// Text sized in metres, drawn in pixels so it stays sharp.
function text(ctx, scale, value, xM, yM, sizeM, { colour, weight = 700, align = 'left' }) {
  ctx.save();
  ctx.scale(1 / scale, 1 / scale);
  ctx.font = `${weight} ${sizeM * scale}px system-ui, -apple-system, "Segoe UI", sans-serif`;
  ctx.fillStyle = colour;
  ctx.textAlign = align;
  ctx.textBaseline = 'middle';
  ctx.fillText(value, xM * scale, yM * scale);
  ctx.restore();
}

// Fine grain on the current canvas: dots of random brightness.
function grain(ctx, random, xM, yM, widthM, heightM, count, sizeM, alpha) {
  for (let i = 0; i < count; i += 1) {
    const light = random() > 0.5;
    ctx.fillStyle = light ? `rgba(255,255,255,${alpha * random()})` : `rgba(0,0,0,${alpha * random()})`;
    ctx.fillRect(xM + random() * widthM, yM + random() * heightM, sizeM, sizeM);
  }
}

// --- Belt surface: one slat, repeated by a TilingSprite ---------------------

export function beltSurfaceCanvas(scale) {
  const { canvas, ctx } = metreCanvas(BELT.slatM, BELT.surfaceM, scale);
  const random = seededRandom(7);
  const width = canvas.width / scale;
  const height = BELT.surfaceM;

  ctx.fillStyle = '#262b31';
  ctx.fillRect(0, 0, width, height);
  grain(ctx, random, 0, 0, width, height, 260, 0.004, 0.18);
  // Raised slat: a lit leading edge and a dark trailing edge.
  ctx.fillStyle = 'rgba(255, 255, 255, 0.09)';
  ctx.fillRect(0, 0, 0.012, height);
  ctx.fillStyle = 'rgba(0, 0, 0, 0.45)';
  ctx.fillRect(0.012, 0, 0.01, height);
  // The upper rail shades the surface just below it.
  const shadow = ctx.createLinearGradient(0, 0, 0, 0.1);
  shadow.addColorStop(0, 'rgba(0, 0, 0, 0.55)');
  shadow.addColorStop(1, 'rgba(0, 0, 0, 0)');
  ctx.fillStyle = shadow;
  ctx.fillRect(0, 0, width, 0.1);
  return canvas;
}

// --- Floor and fixed equipment ---------------------------------------------
//
// Scene canvases cover the whole screen. Their origin is the start of the
// belt on its centre line, so everything is placed in engine metres.

function sceneCanvas(geometry, screenWidth, screenHeight, resolution) {
  const canvas = document.createElement('canvas');
  canvas.width = Math.ceil(screenWidth * resolution);
  canvas.height = Math.ceil(screenHeight * resolution);
  const ctx = canvas.getContext('2d');
  const scale = geometry.pixelsPerMetre * resolution;
  ctx.setTransform(scale, 0, 0, scale, geometry.startX * resolution, geometry.centreY * resolution);
  // Visible area in metres, relative to the origin.
  const view = {
    left: -geometry.startX / geometry.pixelsPerMetre,
    top: -geometry.centreY / geometry.pixelsPerMetre,
    width: screenWidth / geometry.pixelsPerMetre,
    height: screenHeight / geometry.pixelsPerMetre,
  };
  return { canvas, ctx, scale, view };
}

function drawTiles(ctx, view, random) {
  const tile = 0.6;
  const grout = 0.012;
  ctx.fillStyle = '#12171c';
  ctx.fillRect(view.left, view.top, view.width, view.height);
  const firstColumn = Math.floor(view.left / tile);
  const firstRow = Math.floor(view.top / tile);
  for (let column = firstColumn; column * tile < view.left + view.width; column += 1) {
    for (let row = firstRow; row * tile < view.top + view.height; row += 1) {
      const lightness = 15 + random() * 4;
      ctx.fillStyle = `hsl(210, 12%, ${lightness}%)`;
      ctx.fillRect(column * tile + grout / 2, row * tile + grout / 2, tile - grout, tile - grout);
    }
  }
  grain(ctx, random, view.left, view.top, view.width, view.height,
    Math.round(view.width * view.height * 350), 0.012, 0.12);
}

function drawLighting(ctx, view, lengthM) {
  // A soft pool of light over the belt, darker towards the screen edges.
  const centreX = lengthM / 2;
  const radius = Math.max(view.width, view.height) * 0.65;
  const light = ctx.createRadialGradient(centreX, 0, 0, centreX, 0, radius);
  light.addColorStop(0, 'rgba(160, 190, 215, 0.10)');
  light.addColorStop(0.5, 'rgba(0, 0, 0, 0)');
  light.addColorStop(1, 'rgba(0, 0, 0, 0.45)');
  ctx.fillStyle = light;
  ctx.fillRect(view.left, view.top, view.width, view.height);
}

function drawSafetyLines(ctx, lengthM) {
  const offset = BELT_WIDTH_M / 2 + 0.35;
  ctx.fillStyle = 'rgba(232, 184, 47, 0.75)';
  for (const y of [-offset - 0.05, offset]) ctx.fillRect(-0.3, y, lengthM + 0.6, 0.05);
}

function drawCheckInDesk(ctx, scale) {
  // Counter body standing 1 m tall, with a steel weighing plate in front.
  ctx.save();
  castShadow(ctx, scale, 0.9, 0.55);
  ctx.fillStyle = '#39434d';
  ctx.beginPath();
  ctx.roundRect(-1.55, -1.05, 0.75, 2.1, 0.06);
  ctx.fill();
  ctx.restore();
  const top = ctx.createLinearGradient(-1.55, -1.05, -0.8, 1.05);
  top.addColorStop(0, '#5a6773');
  top.addColorStop(1, '#343d46');
  ctx.fillStyle = top;
  ctx.beginPath();
  ctx.roundRect(-1.55, -1.05, 0.75, 2.1, 0.06);
  ctx.fill();
  ctx.strokeStyle = 'rgba(255, 255, 255, 0.12)';
  ctx.lineWidth = 0.012;
  ctx.stroke();
  // Agent screen on the counter.
  ctx.fillStyle = '#10151a';
  ctx.fillRect(-1.42, -0.55, 0.16, 0.34);
  ctx.fillStyle = 'rgba(117, 215, 192, 0.55)';
  ctx.fillRect(-1.4, -0.53, 0.12, 0.3);

  ctx.save();
  castShadow(ctx, scale, 0.25, 0.45);
  ctx.fillStyle = '#8d979f';
  ctx.fillRect(-0.78, -0.42, 0.62, 0.84);
  ctx.restore();
  const plate = ctx.createLinearGradient(-0.78, -0.42, -0.16, 0.42);
  plate.addColorStop(0, '#c9d1d7');
  plate.addColorStop(1, '#6f7a83');
  ctx.fillStyle = plate;
  ctx.fillRect(-0.78, -0.42, 0.62, 0.84);
  ctx.strokeStyle = 'rgba(0, 0, 0, 0.35)';
  ctx.strokeRect(-0.74, -0.38, 0.54, 0.76);
}

function drawChute(ctx, lengthM) {
  // A steel chute sloping down away from the belt: darker as it descends.
  const start = lengthM + BELT.drumM + 0.02;
  const end = start + 1.25;
  const shape = () => {
    ctx.beginPath();
    ctx.moveTo(start, -0.42);
    ctx.lineTo(end, -0.62);
    ctx.lineTo(end, 0.62);
    ctx.lineTo(start, 0.42);
    ctx.closePath();
  };
  const slope = ctx.createLinearGradient(start, 0, end, 0);
  slope.addColorStop(0, '#7d8891');
  slope.addColorStop(1, '#262d33');
  ctx.fillStyle = slope;
  shape();
  ctx.fill();
  // Raised side lips.
  ctx.strokeStyle = '#b7c1c8';
  ctx.lineWidth = 0.035;
  ctx.beginPath();
  ctx.moveTo(start, -0.42);
  ctx.lineTo(end, -0.62);
  ctx.moveTo(start, 0.42);
  ctx.lineTo(end, 0.62);
  ctx.stroke();
  // Guide lines along the slope.
  ctx.strokeStyle = 'rgba(0, 0, 0, 0.25)';
  ctx.lineWidth = 0.01;
  for (const y of [-0.2, 0, 0.2]) {
    ctx.beginPath();
    ctx.moveTo(start + 0.05, y);
    ctx.lineTo(end - 0.05, y * 1.4);
    ctx.stroke();
  }
}

// Airport wayfinding sign: yellow code box and white caption on a dark panel.
function drawSign(ctx, scale, xM, yM, code, caption) {
  const height = 0.36;
  const width = 0.5 + caption.length * 0.105;
  ctx.save();
  castShadow(ctx, scale, 1.2, 0.5);
  ctx.fillStyle = '#0b0f13';
  ctx.beginPath();
  ctx.roundRect(xM, yM, width, height, 0.05);
  ctx.fill();
  ctx.restore();
  ctx.strokeStyle = 'rgba(255, 255, 255, 0.1)';
  ctx.lineWidth = 0.01;
  ctx.stroke();
  ctx.fillStyle = '#f2c230';
  ctx.beginPath();
  ctx.roundRect(xM + 0.05, yM + 0.05, height - 0.1, height - 0.1, 0.03);
  ctx.fill();
  text(ctx, scale, code, xM + height / 2, yM + height / 2 + 0.005, 0.2, { colour: '#0b0f13', weight: 800, align: 'center' });
  text(ctx, scale, caption, xM + height + 0.04, yM + height / 2 + 0.005, 0.16, { colour: '#f4f6f8', weight: 650 });
}

export function floorCanvas({ geometry, screenWidth, screenHeight, resolution, lengthM, inputCode, outputCode }) {
  const { canvas, ctx, scale, view } = sceneCanvas(geometry, screenWidth, screenHeight, resolution);
  const random = seededRandom(42);
  drawTiles(ctx, view, random);
  drawSafetyLines(ctx, lengthM);

  // The belt stands about 0.7 m above the floor: long shadow down-right.
  ctx.save();
  castShadow(ctx, scale, 0.7, 0.6);
  ctx.fillStyle = '#0b0e11';
  ctx.fillRect(-BELT.drumM, -BELT_WIDTH_M / 2, lengthM + 2 * BELT.drumM, BELT_WIDTH_M);
  ctx.restore();

  drawCheckInDesk(ctx, scale);
  drawChute(ctx, lengthM);
  drawLighting(ctx, view, lengthM);
  drawSign(ctx, scale, -1.55, -BELT_WIDTH_M / 2 - 1.05, inputCode, `Check-in ${inputCode}`);
  drawSign(ctx, scale, lengthM - 0.9, -BELT_WIDTH_M / 2 - 1.05, outputCode, `Output ${outputCode}`);
  return canvas;
}

// --- Belt frame, drawn above the surface -----------------------------------

function drawDrum(ctx, xM) {
  // A roller seen from above: its axis runs across the belt.
  const drum = ctx.createLinearGradient(xM, 0, xM + BELT.drumM, 0);
  drum.addColorStop(0, '#3a4148');
  drum.addColorStop(0.45, '#aeb8c0');
  drum.addColorStop(1, '#2b3137');
  ctx.fillStyle = drum;
  ctx.fillRect(xM, -BELT.surfaceM / 2, BELT.drumM, BELT.surfaceM);
}

function drawRail(ctx, random, lengthM, yM) {
  const x = -BELT.drumM - 0.04;
  const width = lengthM + 2 * (BELT.drumM + 0.04);
  const steel = ctx.createLinearGradient(0, yM, 0, yM + BELT.railM);
  steel.addColorStop(0, '#e1e7eb');
  steel.addColorStop(0.35, '#9ea9b1');
  steel.addColorStop(1, '#58626a');
  ctx.fillStyle = steel;
  ctx.fillRect(x, yM, width, BELT.railM);
  // Brushed metal: faint lines along the rail.
  for (let i = 0; i < 40; i += 1) {
    ctx.fillStyle = `rgba(255, 255, 255, ${0.05 * random()})`;
    ctx.fillRect(x, yM + random() * BELT.railM, width, 0.002);
  }
  ctx.strokeStyle = 'rgba(0, 0, 0, 0.5)';
  ctx.lineWidth = 0.006;
  ctx.strokeRect(x, yM, width, BELT.railM);

  // Bolts and yellow direction chevrons every metre.
  for (let m = 0; m <= lengthM; m += 1) {
    ctx.fillStyle = '#3d454c';
    ctx.beginPath();
    ctx.arc(m, yM + BELT.railM / 2, 0.012, 0, Math.PI * 2);
    ctx.fill();
    if (m < lengthM) {
      const cx = m + 0.5;
      const cy = yM + BELT.railM / 2;
      ctx.strokeStyle = '#f2c230';
      ctx.lineWidth = 0.018;
      ctx.lineJoin = 'round';
      ctx.beginPath();
      ctx.moveTo(cx - 0.02, cy - 0.028);
      ctx.lineTo(cx + 0.02, cy);
      ctx.lineTo(cx - 0.02, cy + 0.028);
      ctx.stroke();
    }
  }
}

export function frameCanvas({ geometry, screenWidth, screenHeight, resolution, lengthM }) {
  const { canvas, ctx } = sceneCanvas(geometry, screenWidth, screenHeight, resolution);
  const random = seededRandom(11);
  drawDrum(ctx, -BELT.drumM);
  drawDrum(ctx, lengthM);
  drawRail(ctx, random, lengthM, -BELT_WIDTH_M / 2);
  drawRail(ctx, random, lengthM, BELT_WIDTH_M / 2 - BELT.railM);
  return canvas;
}

// --- Suitcases -------------------------------------------------------------
//
// The rear edge (engine position_m) is at x = 0 and the bag travels towards
// +x. The canvas has BAG_PADDING_M of room on every side for the shadow.

function bodyPath(ctx, style, lengthM, widthM) {
  const radius = style === 'duffel' ? widthM * 0.45 : 0.055;
  ctx.beginPath();
  ctx.roundRect(0, 0, lengthM, widthM, radius);
}

function drawWheelsAndHandle(ctx, lengthM, widthM) {
  // Parts sticking out of the body: two wheels at the rear, a side handle.
  ctx.fillStyle = '#15181b';
  for (const y of [0.02, widthM - 0.065]) {
    ctx.beginPath();
    ctx.roundRect(-0.025, y, 0.05, 0.045, 0.012);
    ctx.fill();
  }
  ctx.fillStyle = '#1d2125';
  ctx.beginPath();
  ctx.roundRect(lengthM * 0.35, -0.03, lengthM * 0.3, 0.05, 0.02);
  ctx.fill();
}

function drawHardshellDetails(ctx, colour, lengthM, widthM) {
  // Moulded ridges along the shell.
  for (let k = 1; k <= 4; k += 1) {
    const y = (widthM * k) / 5;
    ctx.fillStyle = shade(colour, 0.22);
    ctx.fillRect(0.06, y - 0.006, lengthM - 0.12, 0.006);
    ctx.fillStyle = shade(colour, -0.35);
    ctx.fillRect(0.06, y, lengthM - 0.12, 0.006);
  }
  // Trolley handle housing at the rear.
  ctx.fillStyle = shade(colour, -0.55);
  ctx.beginPath();
  ctx.roundRect(0.02, widthM * 0.28, 0.045, widthM * 0.44, 0.012);
  ctx.fill();
}

function drawDuffelDetails(ctx, colour, lengthM, widthM, random) {
  grain(ctx, random, 0.02, 0.02, lengthM - 0.04, widthM - 0.04, 500, 0.004, 0.15);
  // Straps across the bag, joined by a carry handle.
  ctx.fillStyle = shade(colour, -0.5);
  for (const x of [lengthM * 0.3, lengthM * 0.66]) ctx.fillRect(x, 0.01, 0.035, widthM - 0.02);
  ctx.strokeStyle = shade(colour, -0.6);
  ctx.lineWidth = 0.022;
  ctx.beginPath();
  ctx.ellipse(lengthM * 0.5, widthM * 0.5, lengthM * 0.19, widthM * 0.16, 0, 0, Math.PI * 2);
  ctx.stroke();
  // Zipper along the middle.
  ctx.strokeStyle = 'rgba(230, 230, 230, 0.6)';
  ctx.lineWidth = 0.008;
  ctx.setLineDash([0.012, 0.008]);
  ctx.beginPath();
  ctx.moveTo(0.08, widthM * 0.5);
  ctx.lineTo(lengthM - 0.08, widthM * 0.5);
  ctx.stroke();
  ctx.setLineDash([]);
}

function drawCabinDetails(ctx, colour, lengthM, widthM) {
  // Front pocket with its zipper.
  ctx.fillStyle = shade(colour, 0.1);
  ctx.beginPath();
  ctx.roundRect(0.08, 0.07, lengthM - 0.16, widthM - 0.14, 0.04);
  ctx.fill();
  ctx.strokeStyle = shade(colour, -0.45);
  ctx.lineWidth = 0.008;
  ctx.setLineDash([0.012, 0.008]);
  ctx.stroke();
  ctx.setLineDash([]);
  ctx.fillStyle = shade(colour, -0.55);
  ctx.beginPath();
  ctx.roundRect(0.02, widthM * 0.3, 0.04, widthM * 0.4, 0.012);
  ctx.fill();
}

function drawTag(ctx, scale, lengthM, widthM, label) {
  // White bag tag with a barcode and the destination: readable whatever the colour.
  const width = 0.19;
  const height = 0.15;
  const x = lengthM - width - 0.06;
  const y = (widthM - height) / 2;
  ctx.save();
  castShadow(ctx, scale, 0.02, 0.45);
  ctx.fillStyle = '#f5f2e9';
  ctx.beginPath();
  ctx.roundRect(x, y, width, height, 0.02);
  ctx.fill();
  ctx.restore();
  ctx.fillStyle = '#1b1f23';
  let bar = x + 0.02;
  for (const w of [0.006, 0.003, 0.008, 0.003, 0.005, 0.003, 0.007]) {
    ctx.fillRect(bar, y + 0.025, w, height - 0.05);
    bar += w + 0.004;
  }
  text(ctx, scale, label, x + width - 0.05, y + height / 2 + 0.004, 0.12, { colour: '#1b1f23', weight: 800, align: 'center' });
}

export function suitcaseCanvas({ style, colour, lengthM, widthM, label, scale, seed }) {
  const pad = BAG_PADDING_M;
  const { canvas, ctx } = metreCanvas(lengthM + 2 * pad, widthM + 2 * pad, scale);
  const random = seededRandom(seed);
  ctx.translate(pad, pad);

  if (style !== 'duffel') drawWheelsAndHandle(ctx, lengthM, widthM);

  // The body with its shadow on the belt, then the lit surface.
  ctx.save();
  castShadow(ctx, scale, 0.18, 0.6);
  ctx.fillStyle = colour;
  bodyPath(ctx, style, lengthM, widthM);
  ctx.fill();
  ctx.restore();
  const surface = ctx.createLinearGradient(0, 0, lengthM * 0.7, widthM);
  surface.addColorStop(0, shade(colour, 0.28));
  surface.addColorStop(0.55, colour);
  surface.addColorStop(1, shade(colour, -0.32));
  ctx.fillStyle = surface;
  bodyPath(ctx, style, lengthM, widthM);
  ctx.fill();

  ctx.save();
  bodyPath(ctx, style, lengthM, widthM);
  ctx.clip();
  if (style === 'hardshell') drawHardshellDetails(ctx, colour, lengthM, widthM);
  else if (style === 'duffel') drawDuffelDetails(ctx, colour, lengthM, widthM, random);
  else drawCabinDetails(ctx, colour, lengthM, widthM);
  ctx.restore();

  // Dark outline and a highlight along the lit top edge.
  ctx.strokeStyle = shade(colour, -0.55);
  ctx.lineWidth = 0.012;
  bodyPath(ctx, style, lengthM, widthM);
  ctx.stroke();
  ctx.strokeStyle = 'rgba(255, 255, 255, 0.28)';
  ctx.lineWidth = 0.008;
  ctx.beginPath();
  ctx.moveTo(0.07, 0.012);
  ctx.lineTo(lengthM - 0.07, 0.012);
  ctx.stroke();

  drawTag(ctx, scale, lengthM, widthM, label);
  return canvas;
}
