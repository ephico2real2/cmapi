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

// The `properties` of the JSON Schema of a metadata map: `properties` under `labels` or `annotations`, in an object that
// says it is the schema of an object (`type: object`). A labels map of a body that nests a `properties` object is a
// misuse, and stays refused, as it was before #336.
function inMapSchema(path, parent) {
  const [first, second] = owners(path);
  return first === 'properties' && MAPS.has(second) &&
    parent !== null && typeof parent === 'object' && !Array.isArray(parent) && parent.type === 'object';
}

// parent: the object or list that holds `node`, so the schema test can read the map's own `type`.
function walk(node, path, inExample, out, parent) {
  if (Array.isArray(node)) {
    node.forEach((item, index) => walk(item, [...path, index], inExample, out, node));
    return;
  }
  if (node === null || typeof node !== 'object') return;
  for (const [key, value] of Object.entries(node)) {
    if (inExample && key.startsWith(PREFIX) && !MAPS.has(owner(path)) && !inMapSchema(path, parent)) {
      out.push({ message: `the key ${key} is in an example of ${owner(path)}, and cmapi.net/ keys are only in labels and annotations`, path: [...path, key] });
    }
    walk(value, [...path, key], inExample || EXAMPLE_KEYS.has(key), out, node);
  }
}

export default (document) => {
  const out = [];
  walk(document, [], false, out, null);
  return out;
};
