// Map signals: belt status lights and the wrong-arrival signal at outputs.
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { addWrongExits, beltLights, WRONG_EXIT_SIGNAL_S, wrongExitSignals } from '../src/signals.js';

function belt(id, { stopped = false, faulty = false, congested = false } = {}) {
  return { id, stopped, faulty, congested };
}

function alarm(id, kind, state, element, bag = null) {
  return {
    id, kind, severity: kind === 'belt_fault' ? 'error' : 'warning', state,
    element_id: element, baggage_id: bag,
  };
}

test('each belt lights its worst condition: fault, then warning, then stop, else running', () => {
  const lights = beltLights({
    belts: [
      belt('a'), belt('b', { stopped: true }), belt('c', { congested: true, stopped: true }),
      belt('d', { faulty: true, congested: true, stopped: true }), belt('e'),
    ],
    alarms: [
      alarm(1, 'congestion', 'acknowledged', 'c'), alarm(2, 'belt_fault', 'acknowledged', 'd'),
      // A bag waiting on belt e: a warning on its belt.
      alarm(3, 'prolonged_wait', 'acknowledged', 'e', 'bag-4'),
    ],
  });
  assert.deepEqual(Object.fromEntries([...lights].map(([id, light]) => [id, light.state])), {
    a: 'running', b: 'stopped', c: 'warning', d: 'fault', e: 'warning',
  });
  assert.ok([...lights.values()].every((light) => !light.blinking));
});

test('a light blinks while an alarm of its belt is not acknowledged', () => {
  const snapshot = (states) => ({
    belts: [belt('a', { faulty: true, congested: true })],
    alarms: [alarm(1, 'belt_fault', states[0], 'a'), alarm(2, 'congestion', states[1], 'a')],
  });
  assert.equal(beltLights(snapshot(['active', 'acknowledged'])).get('a').blinking, true);
  assert.equal(beltLights(snapshot(['acknowledged', 'active'])).get('a').blinking, true);
  assert.equal(beltLights(snapshot(['acknowledged', 'acknowledged'])).get('a').blinking, false);
  // A resolved alarm no longer counts, and the light follows the belt's state.
  const repaired = beltLights({ belts: [belt('a')], alarms: [alarm(1, 'belt_fault', 'resolved', 'a')] });
  assert.deepEqual(repaired.get('a'), { state: 'running', blinking: false });
});

function exitEvent(id, output, timeS, kind = 'wrong_exit') {
  return { id, kind, element_id: output, baggage_id: `bag-${id}`, time_s: timeS };
}

test('only wrong exits are signalled, and old ones are dropped', () => {
  let arrivals = addWrongExits([], {
    time_s: 10, events: [exitEvent(1, 'output-2', 9.5), exitEvent(2, 'line-1', 9.6, 'belt_stopped')],
  });
  assert.deepEqual(arrivals, [{ outputId: 'output-2', timeS: 9.5 }]);
  arrivals = addWrongExits(arrivals, { time_s: 40, events: [exitEvent(3, 'output-1', 39)] });
  assert.deepEqual(arrivals, [{ outputId: 'output-1', timeS: 39 }]);
});

test('an output signals from the arrival, in displayed time, for a few seconds', () => {
  const arrivals = [{ outputId: 'output-1', timeS: 20 }];
  // Not before the bag arrives in the picture (it runs behind the snapshots).
  assert.equal(wrongExitSignals(arrivals, 19.9).size, 0);
  assert.equal(wrongExitSignals(arrivals, 20).get('output-1'), 0);
  assert.equal(wrongExitSignals(arrivals, 20 + WRONG_EXIT_SIGNAL_S / 2).get('output-1'), 0.5);
  assert.equal(wrongExitSignals(arrivals, 20 + WRONG_EXIT_SIGNAL_S).size, 0);
});

test('a second wrong arrival at the same output starts its signal again', () => {
  const arrivals = [{ outputId: 'output-1', timeS: 20 }, { outputId: 'output-1', timeS: 21.5 }];
  assert.equal(wrongExitSignals(arrivals, 22.25).get('output-1'), 0.25);
});
