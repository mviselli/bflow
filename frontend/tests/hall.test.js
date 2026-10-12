// The hall view's projection (geometry.js) and solid shapes (hallshapes.js).
import assert from 'node:assert/strict';
import { test } from 'node:test';
import {
  HALL_CAMERA, HALL_PADDING_PX, HALL_SLAB_M, HALL_WALL_M, MAX_ZOOM, clampHallCamera, hallFloor,
  hallProjection, hallView, panHallBy, zoomHallAround,
} from '../src/geometry.js';
import {
  faceVisible, outwardEdges, prism, rect, ring, shadeColour, sideShade,
} from '../src/hallshapes.js';

const near = (actual, expected, tolerance = 1e-9) => assert.ok(Math.abs(actual - expected) <= tolerance,
  `${actual} is not ${expected}`);

// A plant 30 m by 10 m: only its bounds matter here.
const layout = {
  inputs: [{ id: 'input-a', position: { x_m: 0, y_m: 0 } }],
  merges: [],
  sorters: [],
  outputs: [{ id: 'output-1', position: { x_m: 30, y_m: 10 } }],
  belts: [],
};

test('the floor slab is the plant bounds plus the margin', () => {
  assert.deepEqual(hallFloor(layout), [{ x: -3, y: -3 }, { x: 33, y: -3 }, { x: 33, y: 13 }, { x: -3, y: 13 }]);
});

test('seen straight down without a turn the hall projection is the map', () => {
  const flat = hallProjection(0, Math.PI / 2);
  const { u, v } = flat.units(4, 7, 2);
  near(u, 4);
  near(v, 7);  // a height moves nothing when looking straight down
});

test('every projection can be inverted at a given height', () => {
  for (const yaw of [HALL_CAMERA.yaw, 0.3, Math.PI * 0.75]) {
    const projection = hallProjection(yaw, HALL_CAMERA.elevation);
    for (const z of [0, 0.7, 2]) {
      const { u, v } = projection.units(12.5, -3.25, z);
      const back = projection.fromUnits(u, v, z);
      near(back.x_m, 12.5);
      near(back.y_m, -3.25);
    }
  }
});

test('height moves a point up the screen and depth grows towards the viewer', () => {
  const projection = hallProjection(HALL_CAMERA.yaw, HALL_CAMERA.elevation);
  assert.ok(projection.units(5, 5, 1).v < projection.units(5, 5, 0).v);
  const { toward } = projection;
  assert.ok(projection.depth(5 + toward.x, 5 + toward.y) > projection.depth(5, 5));
  // The default view looks from the map's bottom-left (south-west) corner.
  assert.ok(toward.x < 0 && toward.y > 0);
});

test('the fitted hall fills the screen inside the padding, whatever the direction', () => {
  for (const yaw of [HALL_CAMERA.yaw, HALL_CAMERA.yaw + Math.PI / 2, HALL_CAMERA.yaw + Math.PI]) {
    const view = hallView(layout, 800, 500, { ...HALL_CAMERA, yaw });
    const points = hallFloor(layout).flatMap(({ x, y }) => [-HALL_SLAB_M, HALL_WALL_M]
      .map((z) => view.toScreen({ x_m: x, y_m: y }, z)));
    const xs = points.map((p) => p.x);
    const ys = points.map((p) => p.y);
    const left = Math.min(...xs);
    const right = Math.max(...xs);
    const top = Math.min(...ys);
    const bottom = Math.max(...ys);
    assert.ok(left >= HALL_PADDING_PX - 1e-6 && right <= 800 - HALL_PADDING_PX + 1e-6);
    assert.ok(top >= HALL_PADDING_PX - 1e-6 && bottom <= 500 - HALL_PADDING_PX + 1e-6);
    // Touching the padding on one axis, centred on both.
    assert.ok(Math.abs(left - HALL_PADDING_PX) < 1e-6 || Math.abs(top - HALL_PADDING_PX) < 1e-6);
    near((left + right) / 2, 400, 1e-6);
    near((top + bottom) / 2, 250, 1e-6);
  }
});

test('toMap at a height undoes toScreen at the same height', () => {
  const view = hallView(layout, 800, 500, { ...HALL_CAMERA, zoom: 2.5, centre: { x_m: 10, y_m: 4 } });
  const screen = view.toScreen({ x_m: 7, y_m: 2 }, 0.7);
  const back = view.toMap(screen, 0.7);
  near(back.x_m, 7, 1e-9);
  near(back.y_m, 2, 1e-9);
  // The camera's centre is at the middle of the screen.
  const middle = view.toScreen({ x_m: 10, y_m: 4 });
  near(middle.x, 400, 1e-9);
  near(middle.y, 250, 1e-9);
});

test('the hall camera keeps its zoom within limits and the hall on screen', () => {
  // Far beyond the top-right corner of the screen in the default view.
  const far = { x_m: 500, y_m: -100 };
  assert.equal(clampHallCamera(layout, { ...HALL_CAMERA, zoom: 0.2 }, 800, 500).zoom, 1);
  assert.equal(clampHallCamera(layout, { ...HALL_CAMERA, zoom: 50 }, 800, 500).zoom, MAX_ZOOM);
  // Fitted, there is nowhere to go: the centre is the fitted one.
  const fitted = hallView(layout, 800, 500);
  const clamped = clampHallCamera(layout, { ...HALL_CAMERA, centre: far }, 800, 500);
  const centre = fitted.units(clamped.centre.x_m, clamped.centre.y_m);
  near(centre.u, fitted.centre.u, 1e-6);
  near(centre.v, fitted.centre.v, 1e-6);
  // Zoomed in, dragged far away: the view stops at the edge of the fitted area.
  const zoomed = clampHallCamera(layout, { ...HALL_CAMERA, zoom: 4, centre: far }, 800, 500);
  const view = hallView(layout, 800, 500, zoomed);
  const corner = fitted.toMap({ x: 800, y: 0 });
  const shown = view.toScreen(corner);
  near(shown.x, 800, 1e-6);
  near(shown.y, 0, 1e-6);
});

test('zooming keeps the floor point under the pointer and dragging moves the view', () => {
  const pointer = { x: 610, y: 140 };
  const before = hallView(layout, 800, 500, HALL_CAMERA);
  const under = before.toMap(pointer);
  const camera = zoomHallAround(layout, HALL_CAMERA, 800, 500, pointer, 2);
  assert.equal(camera.zoom, 2);
  const after = hallView(layout, 800, 500, camera).toScreen(under);
  near(after.x, pointer.x, 1e-6);
  near(after.y, pointer.y, 1e-6);

  const moved = panHallBy(layout, camera, 800, 500, -30, 20);
  const shifted = hallView(layout, 800, 500, moved).toScreen(under);
  near(shifted.x, pointer.x - 30, 1e-6);
  near(shifted.y, pointer.y + 20, 1e-6);
  // A turn keeps the camera's zoom and centre: it turns around that point.
  const turned = clampHallCamera(layout, { ...moved, yaw: moved.yaw + Math.PI / 2 }, 800, 500);
  assert.equal(turned.zoom, 2);
});

test('footprint edges have outward normals whatever the winding', () => {
  const square = [{ x: 0, y: 0 }, { x: 1, y: 0 }, { x: 1, y: 1 }, { x: 0, y: 1 }];
  for (const footprint of [square, [...square].reverse()]) {
    const normals = outwardEdges(footprint).map(({ a, b, nx, ny }) => ({
      mid: { x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 }, nx, ny,
    }));
    for (const { mid, nx, ny } of normals) {
      assert.ok(nx * (mid.x - 0.5) + ny * (mid.y - 0.5) > 0);
      near(Math.hypot(nx, ny), 1);
    }
  }
});

test('faces turned to the viewer are drawn and faces turned to the light are lighter', () => {
  const toward = { x: -Math.SQRT1_2, y: Math.SQRT1_2 };
  assert.ok(faceVisible(-1, 0, toward));
  assert.ok(faceVisible(0, 1, toward));
  assert.ok(!faceVisible(1, 0, toward));
  assert.ok(!faceVisible(0, -1, toward));
  // The light comes from the map's top-left.
  assert.ok(sideShade(-0.5, -0.8) > sideShade(1, 0));
  assert.ok(sideShade(-0.5, -0.8) <= 0.85 && sideShade(1, 0) >= 0.5);
});

test('colours are shaded darker below 1 and towards white above', () => {
  assert.equal(shadeColour('#808080', 1), 0x808080);
  assert.equal(shadeColour('#808080', 0.5), 0x404040);
  assert.equal(shadeColour(0x000000, 2), 0xffffff);
  assert.equal(shadeColour('#ff0000', 1.5), 0xff8080);
});

test('rectangles follow their frame and rings are centred', () => {
  const corners = rect({ x_m: 1, y_m: 2 }, Math.PI / 2, 0, 3, -0.5, 0.5);
  // (3, -0.5) in the frame: x points down the map, y to its right (-x).
  near(corners[1].x, 1.5);
  near(corners[1].y, 5);
  near(corners[2].x, 0.5);
  const points = ring(4, 4, 1, 6);
  near(points.reduce((sum, p) => sum + p.x, 0) / 6, 4);
  near(points.reduce((sum, p) => sum + p.y, 0) / 6, 4);
});

test('a prism draws only the side faces the viewer sees, then its top', () => {
  const drawn = [];
  const g = { poly(points) { drawn.push(points); return this; }, fill() { return this; } };
  const view = { pt: (x, y, z) => ({ x, y: y - z }), toward: { x: -Math.SQRT1_2, y: Math.SQRT1_2 } };
  prism(g, view, rect({ x_m: 0, y_m: 0 }, 0, 0, 2, 0, 1), 0, 1, '#888888');
  // Two sides (left and bottom of the map's square) and the top.
  assert.equal(drawn.length, 3);
});
