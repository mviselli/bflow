// Charts on the Indicators page: the plant's main counts over simulated time.
//
// The samples are the engine's (one per simulated second, sent once by the
// server in the snapshots): the page only keeps them and draws them, it
// never counts anything itself. Like the engine it keeps the last
// MAX_SAMPLES (10 simulated minutes) and starts over on a new run.
//
// addSeries(), timeRange(), niceMax(), timeTicks(), sampleAt() and
// linePath() are pure (tested with node --test); createCharts() draws them
// as SVG.

import { isNewRun } from './playback.js';

export const MAX_SAMPLES = 600;
// The time axis spans at least this many simulated seconds, so that the
// first samples of a run do not fill the whole width.
export const MIN_SPAN_S = 60;

// Each chart: its title, a caption, and its lines (key in the samples,
// name, colour token). Bags in transit and waiting share one axis (both are
// bags); deliveries per minute are a different measure, so another chart.
export const CHARTS = [
  {
    id: 'plant',
    title: 'Bags in the plant',
    caption: 'on the belts, and queued at the desks',
    lines: [
      { key: 'in_transit', name: 'In transit', colour: 'var(--series-transit)' },
      { key: 'waiting', name: 'Waiting', colour: 'var(--series-waiting)' },
    ],
  },
  {
    id: 'deliveries',
    title: 'Delivered per minute',
    caption: 'bags at their own exit in the last 60 s',
    lines: [{ key: 'throughput', name: 'Delivered', colour: 'var(--series-delivered)' }],
  },
];

export function emptySeries() {
  return { run: null, tick: 0, samples: [] };
}

// The series after a snapshot: its new samples appended, the latest `max`
// kept. A new run starts from an empty series. `samples` is a new array
// only when it changed, so the caller can redraw only then.
export function addSeries(series, snapshot, max = MAX_SAMPLES) {
  const newRun = series.run !== null && isNewRun(series, snapshot);
  const previous = newRun ? emptySeries() : series;
  const lastTick = previous.samples.at(-1)?.tick ?? -1;
  const added = (snapshot.series ?? []).filter((sample) => sample.tick > lastTick);
  let samples = previous.samples;
  if (added.length > 0 || newRun) samples = [...samples, ...added].slice(-max);
  return { run: snapshot.run, tick: snapshot.tick, samples };
}

// Simulated seconds shown on the time axis: from the first sample kept, at
// least MIN_SPAN_S wide.
export function timeRange(samples) {
  const start = samples[0]?.time_s ?? 0;
  const end = samples.at(-1)?.time_s ?? 0;
  return [start, Math.max(end, start + MIN_SPAN_S)];
}

// The top of a value axis: a round number (1, 2 or 5 × a power of ten) at
// or above the largest value, at least 5, and its ticks from 0.
export function niceMax(value) {
  const target = Math.max(value, 5);
  let step = 10 ** Math.floor(Math.log10(target / 4));
  for (const factor of [1, 2, 5, 10]) {
    if (target / (step * factor) <= 4) {
      step *= factor;
      break;
    }
  }
  const max = Math.ceil(target / step) * step;
  const ticks = [];
  for (let tick = 0; tick <= max + 1e-9; tick += step) ticks.push(tick);
  return { max, ticks };
}

const TIME_STEPS_S = [10, 15, 30, 60, 120, 300, 600];

// Round times inside [start, end] for the time axis, at most `count` of them.
export function timeTicks(start, end, count = 5) {
  const step = TIME_STEPS_S.find((candidate) => (end - start) / candidate <= count) ?? 600;
  const ticks = [];
  for (let time = Math.ceil(start / step) * step; time <= end + 1e-9; time += step) ticks.push(time);
  return ticks;
}

// "1:30" for 90 simulated seconds.
export function formatMinutes(seconds) {
  const minutes = Math.floor(seconds / 60);
  return `${minutes}:${String(Math.round(seconds - minutes * 60)).padStart(2, '0')}`;
}

// The sample nearest to a time, or null without samples.
export function sampleAt(samples, timeS) {
  let nearest = null;
  for (const sample of samples) {
    if (nearest === null || Math.abs(sample.time_s - timeS) < Math.abs(nearest.time_s - timeS)) nearest = sample;
  }
  return nearest;
}

// An SVG path through one key of the samples, with x(time) and y(value).
export function linePath(samples, key, x, y) {
  return samples.map((sample, index) =>
    `${index === 0 ? 'M' : 'L'}${x(sample.time_s).toFixed(1)} ${y(sample[key]).toFixed(1)}`).join(' ');
}

const SVG = 'http://www.w3.org/2000/svg';
const HEIGHT = 150;
// Room for the value labels on the left and the time labels below.
const MARGIN = { left: 30, right: 10, top: 8, bottom: 22 };

function svgElement(name, attributes = {}, parent = null) {
  const element = document.createElementNS(SVG, name);
  for (const [key, value] of Object.entries(attributes)) element.setAttribute(key, value);
  parent?.append(element);
  return element;
}

// One chart: title, legend with the latest values, the plot and a tooltip
// following a crosshair (pointer or arrow keys).
function chartFigure(chart) {
  const figure = document.createElement('figure');
  figure.className = 'chart';
  const head = document.createElement('figcaption');
  const title = document.createElement('h4');
  title.textContent = chart.title;
  const caption = document.createElement('p');
  caption.textContent = chart.caption;
  head.append(title, caption);
  const legend = document.createElement('ul');
  legend.className = 'chart-legend';
  const latest = {};
  for (const line of chart.lines) {
    const item = document.createElement('li');
    const key = document.createElement('i');
    key.style.background = line.colour;
    const name = document.createElement('span');
    name.textContent = line.name;
    const value = document.createElement('b');
    item.append(key, name, value);
    legend.append(item);
    latest[line.key] = value;
  }
  // A single line needs no legend box: the title names it; keep its value.
  if (chart.lines.length === 1) legend.classList.add('single');
  head.append(legend);

  const plot = document.createElement('div');
  plot.className = 'chart-plot';
  const svg = svgElement('svg', { height: HEIGHT, tabindex: '0', role: 'img' }, plot);
  const tooltip = document.createElement('div');
  tooltip.className = 'chart-tooltip';
  tooltip.hidden = true;
  plot.append(tooltip);
  const empty = document.createElement('p');
  empty.className = 'chart-empty';
  empty.textContent = 'Start the simulation to draw the chart.';
  plot.append(empty);
  figure.append(head, plot);
  return { chart, figure, svg, tooltip, empty, latest, hover: null };
}

function draw(part, samples) {
  const { chart, svg, tooltip, empty, latest } = part;
  const width = svg.parentElement.clientWidth;
  for (const line of chart.lines) latest[line.key].textContent = samples.length ? String(samples.at(-1)[line.key]) : '—';
  empty.hidden = samples.length > 1;
  svg.replaceChildren();
  if (width === 0 || samples.length < 2) {
    tooltip.hidden = true;
    return;
  }
  svg.setAttribute('width', width);
  svg.setAttribute('viewBox', `0 0 ${width} ${HEIGHT}`);
  const [start, end] = timeRange(samples);
  const { max, ticks } = niceMax(Math.max(...chart.lines.flatMap((line) => samples.map((s) => s[line.key]))));
  const left = MARGIN.left;
  const right = width - MARGIN.right;
  const bottom = HEIGHT - MARGIN.bottom;
  const x = (time) => left + ((time - start) / (end - start)) * (right - left);
  const y = (value) => bottom - (value / max) * (bottom - MARGIN.top);

  const grid = svgElement('g', { class: 'grid' }, svg);
  for (const value of ticks) {
    svgElement('line', { x1: left, x2: right, y1: y(value), y2: y(value), class: value === 0 ? 'baseline' : '' }, grid);
    const label = svgElement('text', { x: left - 6, y: y(value) + 4, 'text-anchor': 'end' }, grid);
    label.textContent = String(value);
  }
  for (const time of timeTicks(start, end)) {
    const label = svgElement('text', { x: x(time), y: HEIGHT - 6, 'text-anchor': 'middle' }, grid);
    label.textContent = formatMinutes(time);
  }
  for (const line of chart.lines) {
    svgElement('path', { d: linePath(samples, line.key, x, y), class: 'line', style: `stroke: ${line.colour}` }, svg);
    const last = samples.at(-1);
    svgElement('circle', { cx: x(last.time_s), cy: y(last[line.key]), r: 4, class: 'dot', style: `fill: ${line.colour}` }, svg);
  }
  const newest = samples.at(-1);
  svg.setAttribute('aria-label', `${chart.title} over the last ${formatMinutes(end - start)} of simulated time. Now: `
    + chart.lines.map((line) => `${line.name} ${newest[line.key]}`).join(', '));

  // Crosshair and tooltip at the hovered sample, kept across redraws.
  const cross = svgElement('g', { class: 'crosshair' }, svg);
  const showAt = (sample) => {
    part.hover = sample ? sample.tick : null;
    cross.replaceChildren();
    tooltip.hidden = sample === null;
    if (sample === null) return;
    svgElement('line', { x1: x(sample.time_s), x2: x(sample.time_s), y1: MARGIN.top, y2: bottom }, cross);
    for (const line of chart.lines) {
      svgElement('circle', { cx: x(sample.time_s), cy: y(sample[line.key]), r: 4, class: 'dot', style: `fill: ${line.colour}` }, cross);
    }
    const time = document.createElement('span');
    time.className = 'time';
    time.textContent = formatMinutes(sample.time_s);
    const rows = chart.lines.map((line) => {
      const row = document.createElement('span');
      const key = document.createElement('i');
      key.style.background = line.colour;
      const value = document.createElement('b');
      value.textContent = String(sample[line.key]);
      const name = document.createElement('span');
      name.textContent = line.name;
      row.append(key, value, name);
      return row;
    });
    tooltip.replaceChildren(time, ...rows);
    // Beside the crosshair, on the side with more room.
    const at = x(sample.time_s);
    tooltip.style.left = at > width / 2 ? '' : `${at + 10}px`;
    tooltip.style.right = at > width / 2 ? `${width - at + 10}px` : '';
  };
  svg.onpointermove = (event) => {
    const bounds = svg.getBoundingClientRect();
    const time = start + ((event.clientX - bounds.left - left) / (right - left)) * (end - start);
    showAt(sampleAt(samples, time));
  };
  svg.onpointerleave = () => showAt(null);
  svg.onblur = () => showAt(null);
  svg.onkeydown = (event) => {
    if (event.key !== 'ArrowLeft' && event.key !== 'ArrowRight') return;
    event.preventDefault();
    const index = samples.findIndex((sample) => sample.tick === part.hover);
    const from = index < 0 ? samples.length - 1 : index + (event.key === 'ArrowLeft' ? -1 : 1);
    showAt(samples[Math.max(0, Math.min(samples.length - 1, from))]);
  };
  const hovered = samples.find((sample) => sample.tick === part.hover) ?? null;
  showAt(hovered);
}

export function createCharts(element) {
  const parts = CHARTS.map(chartFigure);
  element.append(...parts.map((part) => part.figure));
  let series = emptySeries();
  const redraw = () => { for (const part of parts) draw(part, series.samples); };
  // Drawn at the panel's width, again when it changes (or the page is shown).
  new ResizeObserver(redraw).observe(element);
  return {
    setSnapshot(snapshot) {
      const next = addSeries(series, snapshot);
      const changed = next.samples !== series.samples;
      // A new run: no crosshair left on a sample of the old one.
      if (next.run !== series.run) for (const part of parts) part.hover = null;
      series = next;
      if (changed) redraw();
    },
  };
}
