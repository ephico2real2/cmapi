// Each example of a problem response is a full RFC 9457 problem of cmapi, with the status of the response that holds it.
const FIELDS = ['type', 'title', 'status', 'detail', 'code'];

export default (response, _options, context) => {
  const status = Number(context.path[context.path.length - 1]);
  const media = ((response || {}).content || {})['application/problem+json'];
  if (!media) return [];                       // cmapi-problem-media-type reports the missing media type
  const examples = media.examples;
  if (examples === null || typeof examples !== 'object' || Object.keys(examples).length === 0) {
    return [{ message: `the ${status} response has no named example of a problem`, path: [...context.path, 'content', 'application/problem+json'] }];
  }
  const out = [];
  for (const [name, example] of Object.entries(examples)) {
    const value = (example || {}).value, path = [...context.path, 'content', 'application/problem+json', 'examples', name];
    if (value === null || typeof value !== 'object') {
      out.push({ message: `the example ${name} has no value`, path });
      continue;
    }
    const missing = FIELDS.filter((f) => value[f] === undefined);
    if (missing.length) out.push({ message: `the example ${name} has no ${missing.join(', ')}`, path });
    if (value.status !== undefined && value.status !== status) {
      out.push({ message: `the example ${name} has status ${value.status} in a ${status} response`, path });
    }
    if (value.code !== undefined && value.code !== name) {
      out.push({ message: `the example ${name} has the code ${value.code}`, path });
    }
    if (typeof value.type === 'string' && value.code !== undefined && !value.type.endsWith(`/${value.code}`)) {
      out.push({ message: `the example ${name} has a type that does not end with its code ${value.code}`, path });
    }
  }
  return out;
};
