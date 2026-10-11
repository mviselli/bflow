// Charts: the engine's samples kept per run, axes and paths.
import assert from 'node:assert/strict';
import { test } from 'node:test';
import {
  MAX_SAMPLES, addSeries, emptySeries, formatMinutes, linePath, niceMax, sampleAt, timeRange, timeTicks,
} from '../src/charts.js';

const sample = (tick, extra = {}) => ({
  tick, time_s: tick / 20, in_transit: tick / 20, waiting: 0, correctly_delivered: 0, misdelivered: 0, throughput: 0, ...extra,
});
const snapshot = (run, tick, ticks) => ({ run, tick, series: ticks.map((t) => sample(t)) });

test('samples are appended once each, in order', () => {
  let series = addSeries(emptySeries(), snapshot(1, 40, [0, 20, 40]));
  series = addSeries(series, snapshot(1, 45, []));
  const unchanged = series.samples;
  series = addSeries(series, snapshot(1, 50, []));
  assert.equal(series.samples, unchanged, 'no new sample: the same array, nothing to redraw');
  // A reconnection sends every sample still kept again: only new ones are added.
  series = addSeries(series, snapshot(1, 60, [0, 20, 40, 60]));
  assert.deepEqual(series.samples.map((s) => s.tick), [0, 20, 40, 60]);
});

test('a new run starts the series over, even at the same tick', () => {
  let series = addSeries(emptySeries(), snapshot(1, 40, [0, 20, 40]));
  series = addSeries(series, snapshot(2, 0, [0]));
  assert.deepEqual(series.samples.map((s) => s.tick), [0]);
  series = addSeries(series, snapshot(2, 0, []));
  assert.deepEqual([series.run, series.samples.length], [2, 1]);
  // A restarted server (tick going back in the same run number) too.
  series = addSeries(addSeries(emptySeries(), snapshot(1, 100, [0, 100])), snapshot(1, 20, [0, 20]));
  assert.deepEqual(series.samples.map((s) => s.tick), [0, 20]);
});

test('the page keeps at most the last 600 samples, like the engine', () => {
  const ticks = Array.from({ length: 700 }, (_, index) => index * 20);
  const series = addSeries(emptySeries(), snapshot(1, ticks.at(-1), ticks));
  assert.equal(MAX_SAMPLES, 600);
  assert.equal(series.samples.length, 600);
  assert.equal(series.samples[0].tick, 100 * 20);
});

test('the time axis spans at least a minute, then the samples kept', () => {
  assert.deepEqual(timeRange([]), [0, 60]);
  assert.deepEqual(timeRange([sample(0), sample(200)]), [0, 60]);
  assert.deepEqual(timeRange([sample(2000), sample(14000)]), [100, 700]);
  assert.deepEqual(timeTicks(0, 60), [0, 15, 30, 45, 60]);
  assert.deepEqual(timeTicks(100, 700), [120, 240, 360, 480, 600]);
  assert.equal(formatMinutes(0), '0:00');
  assert.equal(formatMinutes(90), '1:30');
  assert.equal(formatMinutes(600), '10:00');
});

test('the value axis ends at a round number above the data, at least 5', () => {
  assert.deepEqual(niceMax(0), { max: 6, ticks: [0, 2, 4, 6] });
  assert.deepEqual(niceMax(34), { max: 40, ticks: [0, 10, 20, 30, 40] });
  assert.deepEqual(niceMax(77), { max: 80, ticks: [0, 20, 40, 60, 80] });
  assert.equal(niceMax(435).max, 600);
  for (const value of [1, 7, 13, 58, 99, 1000]) {
    const { max, ticks } = niceMax(value);
    assert.ok(max >= value && ticks.at(-1) === max && ticks.length <= 5, `${value}`);
  }
});

test('the nearest sample to a time, and a line through one key', () => {
  const samples = [sample(0), sample(20), sample(40)];
  assert.equal(sampleAt(samples, 1.4).tick, 20);
  assert.equal(sampleAt(samples, 99).tick, 40);
  assert.equal(sampleAt([], 3), null);
  assert.equal(linePath(samples, 'in_transit', (t) => t * 10, (v) => 100 - v),
    'M0.0 100.0 L10.0 99.0 L20.0 98.0');
});
