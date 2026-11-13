// The checks that tie an operation to its plugin: the operationId, the one tag, the groups of ReDoc, and the 401 and 403.
const OPERATION_ID = /^[a-z][a-z0-9]*(_[a-z0-9]+)+$/;

function operationId(op) {
  const id = op.operationId, plugin = op['x-cmapi-plugin'];
  if (typeof id !== 'string' || !OPERATION_ID.test(id)) {
    return [{ message: `operationId ${JSON.stringify(id)} is not <plugin>_<function> in lower case with underscores` }];
  }
  if (typeof plugin !== 'string' || !id.startsWith(`${plugin}_`)) {
    return [{ message: `operationId ${id} does not start with its plugin (x-cmapi-plugin: ${JSON.stringify(plugin)})` }];
  }
  return [];
}

function operationTag(op) {
  const tags = op.tags, plugin = op['x-cmapi-plugin'];
  if (!Array.isArray(tags) || tags.length !== 1) {
    return [{ message: `an operation has exactly one tag, and this one has ${JSON.stringify(tags)}` }];
  }
  if (tags[0] !== plugin) {
    return [{ message: `the tag ${tags[0]} is not the operation's plugin (x-cmapi-plugin: ${JSON.stringify(plugin)})` }];
  }
  return [];
}

function groups(document) {
  const tagGroups = document['x-tagGroups'];
  if (!Array.isArray(tagGroups) || tagGroups.length === 0) {
    return [{ message: 'the document has no x-tagGroups, so ReDoc shows no group' }];
  }
  const out = [];
  for (const tag of document.tags || []) {
    const holders = tagGroups.filter((g) => Array.isArray(g.tags) && g.tags.includes(tag.name)).map((g) => g.name);
    if (holders.length !== 1) {
      out.push({ message: `the tag ${tag.name} is in ${holders.length} groups of x-tagGroups (${holders.join(', ') || 'none'}), not in exactly one` });
    }
  }
  const known = new Set((document.tags || []).map((t) => t.name));
  for (const group of tagGroups) {
    for (const name of group.tags || []) {
      if (!known.has(name)) {
        out.push({ message: `the group ${group.name} of x-tagGroups names the tag ${name}, which the document does not define` });
      }
    }
  }
  return out;
}

function securedProblems(op) {
  const out = [], responses = op.responses || {};
  const secured = Array.isArray(op.security) && op.security.length > 0;
  if (secured && !responses['401']) {
    out.push({ message: `${op.operationId} needs a token and does not declare the 401 response` });
  }
  if (op['x-cmapi-permission'] && !responses['403']) {
    out.push({ message: `${op.operationId} needs the permission ${op['x-cmapi-permission']} and does not declare the 403 response` });
  }
  return out;
}

const CHECKS = { operationId, operationTag, groups, securedProblems };

export default (input, options) => {
  if (input === null || typeof input !== 'object') return [];
  return CHECKS[options.check](input);
};
