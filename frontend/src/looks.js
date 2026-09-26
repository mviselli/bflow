// How things are labelled and how each bag looks, without any drawing code.

export const SUITCASE_STYLES = ['hardshell', 'duffel', 'cabin'];
export const SUITCASE_COLOURS = [
  '#2f4f86', '#8c2f3f', '#1f7f74', '#454b55',
  '#c8952f', '#5f6d3a', '#cf6a4f', '#9aa5b1',
];

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

// A bag's look depends only on its identifier, so it never changes on screen.
// The colour is decorative; the tag label carries the destination.
export function suitcaseLook(baggage) {
  const hash = hashString(baggage.id);
  return {
    style: SUITCASE_STYLES[hash % SUITCASE_STYLES.length],
    colour: SUITCASE_COLOURS[(hash >>> 3) % SUITCASE_COLOURS.length],
    label: shortCode(baggage.destination_id),
  };
}
