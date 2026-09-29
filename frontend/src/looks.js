// How things are labelled and how each bag looks, without any drawing code.

export const SUITCASE_STYLES = ['hardshell', 'duffel', 'cabin'];
export const SUITCASE_COLOURS = [
  '#2f4f86', '#8c2f3f', '#1f7f74', '#454b55',
  '#c8952f', '#5f6d3a', '#cf6a4f', '#9aa5b1',
];
// One colour per output, in layout order, shared by its sign and by the tags
// of the bags going there. The code on the tag keeps it readable without
// colour. Yellow is left to the floor markings.
export const DESTINATION_COLOURS = ['#5ec8f2', '#f07fb4', '#9be07a', '#ffa552', '#c9a6ff'];

// Stable number from a string (FNV-1a hash).
export function hashString(text) {
  let hash = 2166136261;
  for (const char of text) hash = Math.imul(hash ^ char.charCodeAt(0), 16777619);
  return hash >>> 0;
}

// "input-a" → "A", "output-1" → "1": the short code shown on signs and tags.
export function shortCode(id) {
  return id.split('-').pop().toUpperCase();
}

// Output id → { code, colour }, for the signs and the bag tags.
export function destinationLooks(outputs) {
  return new Map(outputs.map((output, index) => [output.id, {
    code: shortCode(output.id),
    colour: DESTINATION_COLOURS[index % DESTINATION_COLOURS.length],
  }]));
}

// A bag's look depends only on its identifier and destination, so it never
// changes on screen. The body colour is decorative; the tag carries the
// destination's code and colour.
export function suitcaseLook(baggage, destinations) {
  const hash = hashString(baggage.id);
  const destination = destinations.get(baggage.destination_id)
    ?? { code: shortCode(baggage.destination_id), colour: '#f5f2e9' };
  return {
    style: SUITCASE_STYLES[hash % SUITCASE_STYLES.length],
    colour: SUITCASE_COLOURS[(hash >>> 3) % SUITCASE_COLOURS.length],
    label: destination.code,
    tagColour: destination.colour,
  };
}
