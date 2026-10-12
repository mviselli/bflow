// Solid shapes for the hall view, drawn with flat faces like a scale model.
//
// Every shape is built from prisms: a footprint on the map (a convex polygon,
// metres) raised from one height to another. Only the side faces turned
// towards the viewer are drawn, then the top, so a prism needs no sorting of
// its own faces. Faces are shaded by a light from the top-left of the map,
// the same light as the top-down map: tops take the full colour, side faces
// turned to the light are a little darker and those turned away much darker.
//
// The drawing functions take a `view` = { pt, toward }: pt(x, y, z) gives a
// map point at height z in the drawing's coordinates and `toward` is the
// horizontal direction towards the viewer (geometry.js hallProjection).
// The maths (normals, shading, visibility) is pure and tested.

// Towards the light, on the map (the top-left, as for the map's shadows).
const LIGHT = (() => {
  const length = Math.hypot(0.35, 0.55);
  return { x: -0.35 / length, y: -0.55 / length };
})();

// The edges of a convex footprint, each with its outward normal (unit).
export function outwardEdges(footprint) {
  const centre = footprint.reduce((sum, p) => ({ x: sum.x + p.x / footprint.length, y: sum.y + p.y / footprint.length }),
    { x: 0, y: 0 });
  return footprint.map((a, i) => {
    const b = footprint[(i + 1) % footprint.length];
    const length = Math.hypot(b.x - a.x, b.y - a.y) || 1;
    let nx = (b.y - a.y) / length;
    let ny = -(b.x - a.x) / length;
    if (nx * ((a.x + b.x) / 2 - centre.x) + ny * ((a.y + b.y) / 2 - centre.y) < 0) {
      nx = -nx;
      ny = -ny;
    }
    return { a, b, nx, ny };
  });
}

// Whether a side face with this outward normal is turned towards the viewer.
export function faceVisible(nx, ny, toward) {
  return nx * toward.x + ny * toward.y > 1e-6;
}

// Brightness of a side face (the top is 1): between 0.5 turned away from
// the light and 0.85 facing it.
export function sideShade(nx, ny) {
  return 0.5 + 0.35 * Math.max(0, nx * LIGHT.x + ny * LIGHT.y);
}

// A colour (#rrggbb or a number) times a brightness, as a number for PixiJS.
// Above 1 it mixes towards white.
export function shadeColour(colour, k) {
  const value = typeof colour === 'number' ? colour : parseInt(colour.slice(1), 16);
  const mix = (channel) => Math.round(k <= 1 ? channel * k : channel + (255 - channel) * Math.min(k - 1, 1));
  return (mix(value >> 16) << 16) | (mix((value >> 8) & 255) << 8) | mix(value & 255);
}

// A rectangle in a frame at `origin` turned by `angle` (x along it, y to
// its right): from x0 to x1 and from y0 to y1, as a footprint.
export function rect(origin, angle, x0, x1, y0, y1) {
  const cos = Math.cos(angle);
  const sin = Math.sin(angle);
  return [[x0, y0], [x1, y0], [x1, y1], [x0, y1]].map(([x, y]) => ({
    x: origin.x_m + x * cos - y * sin,
    y: origin.y_m + x * sin + y * cos,
  }));
}

// A regular polygon with `sides` sides around (x, y), for round things.
export function ring(x, y, radius, sides = 8) {
  return Array.from({ length: sides }, (_, i) => {
    const angle = ((i + 0.5) / sides) * 2 * Math.PI;
    return { x: x + radius * Math.cos(angle), y: y + radius * Math.sin(angle) };
  });
}

function fillPoints(g, points, color, alpha = 1) {
  g.poly(points.flatMap((p) => [p.x, p.y])).fill({ color, alpha });
}

// A flat polygon at height z (a footprint).
export function flat(g, view, footprint, z, color, alpha = 1) {
  fillPoints(g, footprint.map((p) => view.pt(p.x, p.y, z)), color, alpha);
}

// A prism from z0 to z1 over a convex footprint: the side faces seen from
// the viewer, shaded, then the top (`top` colour, the side colour by default).
export function prism(g, view, footprint, z0, z1, colour, { top = colour, alpha = 1 } = {}) {
  for (const { a, b, nx, ny } of outwardEdges(footprint)) {
    if (!faceVisible(nx, ny, view.toward)) continue;
    fillPoints(g, [view.pt(a.x, a.y, z0), view.pt(b.x, b.y, z0), view.pt(b.x, b.y, z1), view.pt(a.x, a.y, z1)],
      shadeColour(colour, sideShade(nx, ny)), alpha);
  }
  flat(g, view, footprint, z1, typeof top === 'number' ? top : shadeColour(top, 1), alpha);
}

// A thin vertical panel standing on the segment a → b (map points), from z0
// to z1, `thickness` metres thick: a gate, a barrier tape.
export function panel(g, view, a, b, z0, z1, thickness, colour, options) {
  const length = Math.hypot(b.x - a.x, b.y - a.y) || 1;
  const nx = (-(b.y - a.y) / length) * thickness / 2;
  const ny = ((b.x - a.x) / length) * thickness / 2;
  prism(g, view, [
    { x: a.x + nx, y: a.y + ny }, { x: b.x + nx, y: b.y + ny },
    { x: b.x - nx, y: b.y - ny }, { x: a.x - nx, y: a.y - ny },
  ], z0, z1, colour, options);
}
