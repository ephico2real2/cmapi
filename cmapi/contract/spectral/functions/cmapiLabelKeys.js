// In an example, a key with the prefix cmapi.net/ is only in a labels map or an annotations map, or a property of the JSON
// Schema of one: GET /api/v1/metadata-keys answers that schema (#336), so its example holds labels.properties["cmapi.net/team"].
const PREFIX = 'cmapi.net/';
const MAPS = new Set(['labels', 'annotations']);
const EXAMPLE_KEYS = new Set(['example', 'examples']);

// The names that say what an object is: the keys above it that are not a list index, an example holder or `value`, nearest first.
function owners(path) {
  return path.filter((key) => typeof key !== 'number' && !EXAMPLE_KEYS.has(key) && key !== 'value').reverse();
}
const owner = (path) => owners(path)[0];

// A metadata map, or the `properties` of the schema of one.
function inMap(path) {
  const [first, second] = owners(path);
  return MAPS.has(first) || (first === 'properties' && MAPS.has(second));
}

function walk(node, path, inExample, out) {
  if (Array.isArray(node)) {
    node.forEach((item, index) => walk(item, [...path, index], inExample, out));
    return;
  }
  if (node === null || typeof node !== 'object') return;
  for (const [key, value] of Object.entries(node)) {
    if (inExample && key.startsWith(PREFIX) && !inMap(path)) {
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
