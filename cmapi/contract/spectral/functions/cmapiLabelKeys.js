// In an example, a key with the prefix cmapi.net/ is only in a labels map or an annotations map.
const PREFIX = 'cmapi.net/';
const MAPS = new Set(['labels', 'annotations']);
const EXAMPLE_KEYS = new Set(['example', 'examples']);

// The name that says what an object is: the nearest key above it that is not a list index, an example holder or `value`.
function owner(path) {
  for (let i = path.length - 1; i >= 0; i -= 1) {
    const key = path[i];
    if (typeof key === 'number' || EXAMPLE_KEYS.has(key) || key === 'value') continue;
    return key;
  }
  return undefined;
}

function walk(node, path, inExample, out) {
  if (Array.isArray(node)) {
    node.forEach((item, index) => walk(item, [...path, index], inExample, out));
    return;
  }
  if (node === null || typeof node !== 'object') return;
  for (const [key, value] of Object.entries(node)) {
    if (inExample && key.startsWith(PREFIX) && !MAPS.has(owner(path))) {
      out.push({ message: `the key ${key} is in an example of ${owner(path)}, and cmapi.net/ keys are only in labels and annotations`, path: [...path, key] });
    }
    walk(value, [...path, key], inExample || EXAMPLE_KEYS.has(key), out);
  }
}

export default (document) => {
  const out = [];
  walk(document, [], false, out);
  return out;
};
