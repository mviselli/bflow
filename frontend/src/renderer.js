// Draws the route with PixiJS from the server's layout and snapshots.
//
// Temporary shapes: a belt, a metre scale and one rectangle per bag. Every
// coordinate goes through geometry.js; the renderer never invents movement,
// it redraws the bags where the latest snapshot says they are.

import { Container, Graphics, Text } from 'pixi.js';
import { baggageRect, beltGeometry } from './geometry.js';

const COLORS = {
  belt: 0x2b3a47,
  beltEdge: 0x8fa3b3,
  arrow: 0x3f5566,
  scale: 0x5d7486,
  baggage: 0xd9a441,
  baggageEdge: 0x5a3f0f,
  label: 0xaebfce,
};

function label(text = '', size = 14) {
  return new Text({ text, style: { fill: COLORS.label, fontFamily: 'system-ui, sans-serif', fontSize: size } });
}

export function createRenderer(app) {
  const belt = new Graphics();
  const bags = new Graphics();
  const inputLabel = label();
  const outputLabel = label();
  const scaleStart = label('0 m', 12);
  const scaleEnd = label('', 12);
  const scene = new Container();
  scene.addChild(belt, bags, inputLabel, outputLabel, scaleStart, scaleEnd);
  app.stage.addChild(scene);

  let layout = null;
  let snapshot = null;

  function drawBelt(geometry, conveyor) {
    const { startX, endX, beltTop, beltHeight, centreY } = geometry;
    belt.clear();
    belt.rect(startX, beltTop, endX - startX, beltHeight).fill(COLORS.belt);
    belt.moveTo(startX, beltTop).lineTo(endX, beltTop)
      .moveTo(startX, beltTop + beltHeight).lineTo(endX, beltTop + beltHeight)
      .stroke({ color: COLORS.beltEdge, width: 2 });

    // Direction chevrons every metre, pointing towards the output.
    const size = beltHeight * 0.18;
    for (let m = 0.5; m < conveyor.length_m; m += 1) {
      const x = geometry.positionToX(m);
      belt.moveTo(x - size / 2, centreY - size).lineTo(x + size / 2, centreY)
        .lineTo(x - size / 2, centreY + size);
    }
    belt.stroke({ color: COLORS.arrow, width: 3 });

    // Metre scale under the belt: one tick per metre.
    const scaleY = beltTop + beltHeight + 10;
    for (let m = 0; m <= conveyor.length_m; m += 1) {
      const x = geometry.positionToX(m);
      belt.moveTo(x, scaleY).lineTo(x, scaleY + (m % 5 === 0 ? 10 : 5));
    }
    belt.moveTo(startX, scaleY).lineTo(endX, scaleY).stroke({ color: COLORS.scale, width: 1 });

    scaleStart.position.set(startX - scaleStart.width / 2, scaleY + 12);
    scaleEnd.text = `${conveyor.length_m} m`;
    scaleEnd.position.set(endX - scaleEnd.width / 2, scaleY + 12);
    inputLabel.text = layout.input_id;
    inputLabel.position.set(startX - inputLabel.width - 8, centreY - inputLabel.height / 2);
    outputLabel.text = layout.output_id;
    outputLabel.position.set(endX + 8, centreY - outputLabel.height / 2);
  }

  function drawBaggage(geometry) {
    bags.clear();
    if (!snapshot) return;
    for (const baggage of snapshot.baggage) {
      const { x, y, width, height } = baggageRect(geometry, baggage);
      bags.roundRect(x, y, width, height, Math.min(width, height) * 0.15)
        .fill(COLORS.baggage)
        .stroke({ color: COLORS.baggageEdge, width: 2 });
    }
  }

  function draw() {
    if (!layout) return;
    const conveyor = layout.conveyors[0];
    const geometry = beltGeometry(conveyor.length_m, app.screen.width, app.screen.height);
    drawBelt(geometry, conveyor);
    drawBaggage(geometry);
    app.render();
  }

  app.renderer.on('resize', draw);

  return {
    // A new layout arrives on every (re)connection: forget the old state.
    setLayout(newLayout) {
      layout = newLayout;
      snapshot = null;
      draw();
    },
    setSnapshot(newSnapshot) {
      snapshot = newSnapshot;
      draw();
    },
  };
}
