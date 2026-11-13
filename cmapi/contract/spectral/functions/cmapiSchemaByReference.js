// The schema of a body is a named schema, by reference. Run with `resolved: false`, so a $ref is still a $ref here.
const SCALARS = new Set(['string', 'integer', 'number', 'boolean', 'null']);

function reason(schema) {
  if (schema === null || typeof schema !== 'object' || Array.isArray(schema)) return 'it is not a schema';
  if (typeof schema.$ref === 'string') {
    return schema.$ref.startsWith('#/components/schemas/') ? null : `the reference ${schema.$ref} is not a schema of components`;
  }
  for (const key of ['anyOf', 'oneOf']) {
    if (Array.isArray(schema[key])) {
      const bad = schema[key].map(reason).filter(Boolean);
      return bad.length ? bad[0] : null;
    }
  }
  if (schema.type === 'array') return schema.items === undefined ? 'the list does not say what it holds' : reason(schema.items);
  if (SCALARS.has(schema.type) && schema.properties === undefined) return null;
  if (Object.keys(schema).filter((k) => k !== 'title' && k !== 'description').length === 0) return 'it is empty, so it permits each value';
  return 'it is an inline object, not a reference to a named schema';
}

export default (media, _options, context) => {
  if (media === null || typeof media !== 'object') return [];
  const name = context.path[context.path.length - 1];
  if (media.schema === undefined) return [{ message: `the body ${name} has no schema` }];
  const why = reason(media.schema);
  return why ? [{ message: `the schema of the body ${name} is not a named schema: ${why}`, path: [...context.path, 'schema'] }] : [];
};
