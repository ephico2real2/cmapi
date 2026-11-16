// A parameter has an example (its own, or its schema's). A request body or a response body has an example.
function present(holder) {
  if (holder === null || typeof holder !== 'object') return false;
  if (holder.example !== undefined) return true;
  const examples = holder.examples;
  if (Array.isArray(examples)) return examples.length > 0;
  return examples !== null && typeof examples === 'object' && Object.keys(examples).length > 0;
}

export default (input, options, context) => {
  if (input === null || typeof input !== 'object') return [];
  if (options.of === 'parameter') {
    return present(input) || present(input.schema) ? [] : [{ message: `the ${input.in} parameter ${input.name} has no example` }];
  }
  const path = context.path;
  return present(input) ? [] : [{ message: `the body ${path[path.length - 1]} has no example` }];
};
