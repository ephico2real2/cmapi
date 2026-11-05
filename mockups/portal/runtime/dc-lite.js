/*
 * dc-lite: renders a Claude Design canvas file (*.dc.html) without React or claude.ai.
 *
 * It mirrors what the canvas runtime does for the constructs mockups/portal/Main.dc.html uses, because
 * these details decide the layout: <sc-for> and <sc-if> add no wrapper element, a text hole renders in
 * <span class="sc-interp">, and elements keep their identity by position, as with React's index keys.
 * README.md lists what it does not support.
 */
(function (global) {
  "use strict";

  // The HTML parser moves anything but table parts out of a table, and options out of a select, so
  // <sc-for> inside <tbody> would not survive parsing. These are renamed before parsing and back on render.
  const RAW_PREFIX = "sc-raw-";
  const RAW_TAGS = /(<\/?)(select|table|tbody|thead|tfoot|tr|td|th|caption)(?=[\s>])/gi;
  const HOLE = /\{\{([\s\S]+?)\}\}/g;
  const WHOLE_HOLE = /^\s*\{\{([\s\S]+?)\}\}\s*$/;
  const BOOLEAN_ATTRS = new Set(["checked", "disabled", "hidden", "multiple", "open", "readonly", "required", "selected"]);
  const CONTROLLED = new Set(["INPUT", "TEXTAREA", "SELECT"]);
  const EVENTS = { onclick: "click", onchange: "change", onsubmit: "submit", onkeydown: "keydown" };
  const warned = new Set();

  function warnOnce(message) {
    if (warned.has(message)) return;
    warned.add(message);
    console.warn("[dc-lite] " + message);
  }

  function lookup(scope, path) {
    let value = scope;
    for (const part of path.trim().split(".")) {
      if (value === null || value === undefined) return undefined;
      value = value[part];
    }
    return value;
  }

  function attrGetter(raw) {
    const whole = raw.match(WHOLE_HOLE);
    if (whole) return (scope) => lookup(scope, whole[1]);
    if (!raw.includes("{{")) return () => raw;
    return (scope) => raw.replace(HOLE, (match, path) => {
      const value = lookup(scope, path);
      return value === null || value === undefined ? "" : value;
    });
  }

  function compileText(node) {
    const raw = node.nodeValue;
    if (!raw.includes("{{")) {
      // A whitespace run holding a space stays, because it separates inline elements. A bare newline goes.
      if (!raw.trim() && !raw.includes(" ")) return null;
      return (scope, out, key) => out.push({ key, text: raw });
    }
    const parts = raw.split(HOLE);
    return (scope, out, key) => parts.forEach((part, i) => {
      const partKey = key + ":" + i;
      if (i % 2 === 0) {
        if (part) out.push({ key: partKey, text: part });
        return;
      }
      const value = lookup(scope, part);
      if (value === undefined) {
        warnOnce("{{ " + part.trim() + " }} never resolved; rendered as empty");
      } else if (Array.isArray(value)) {
        value.forEach((item, j) => out.push({ key: partKey + ":" + j, text: String(item) }));
      } else if (value !== null && typeof value !== "boolean") {
        const kids = value === "" ? [] : [{ key: "0", text: String(value) }];
        out.push({ key: partKey, tag: "span", attrs: [["class", "sc-interp"]], kids });
      }
    });
  }

  function compileChildren(parent) {
    return Array.from(parent.childNodes).map(compileNode).filter(Boolean);
  }

  function renderAll(fns, scope, out, prefix) {
    fns.forEach((fn, i) => fn(scope, out, prefix + i));
  }

  function compileFor(el) {
    const listPath = el.getAttribute("list") || "";
    const list = attrGetter(listPath);
    const as = el.getAttribute("as") || "item";
    const fns = compileChildren(el);
    return (scope, out, key) => {
      const items = list(scope);
      if (!Array.isArray(items)) {
        if (items !== null && items !== undefined) warnOnce('sc-for list="' + listPath + '" is not an array');
        return;
      }
      items.forEach((item, i) => {
        const inner = Object.create(scope);
        inner[as] = item;
        inner.$index = i;
        renderAll(fns, inner, out, key + "." + i + ".");
      });
    };
  }

  function compileIf(el) {
    const value = attrGetter(el.getAttribute("value") || "");
    const fns = compileChildren(el);
    return (scope, out, key) => {
      if (value(scope)) renderAll(fns, scope, out, key + ".");
    };
  }

  function compileElement(el) {
    const name = el.localName;
    const tag = name.startsWith(RAW_PREFIX) ? name.slice(RAW_PREFIX.length) : name;
    const getters = Array.from(el.attributes).map((attr) => {
      if (attr.name.startsWith("on") && !EVENTS[attr.name]) {
        throw new Error("dc-lite: unsupported event attribute " + attr.name + " on <" + tag + ">");
      }
      // A boolean attribute written with no value (<input disabled>) is on.
      if (attr.value === "" && BOOLEAN_ATTRS.has(attr.name)) return [attr.name, () => true];
      return [attr.name, attrGetter(attr.value)];
    });
    const fns = compileChildren(el);
    return (scope, out, key) => {
      const kids = [];
      renderAll(fns, scope, kids, "");
      out.push({ key, tag, attrs: getters.map((g) => [g[0], g[1](scope)]), kids });
    };
  }

  function compileNode(node) {
    if (node.nodeType === Node.TEXT_NODE) return compileText(node);
    if (node.nodeType !== Node.ELEMENT_NODE) return null;
    const name = node.localName;
    if (name === "sc-for") return compileFor(node);
    if (name === "sc-if") return compileIf(node);
    if (name === "helmet") return null;
    return compileElement(node);
  }

  function setAttr(el, name, value) {
    if (name === "style") {
      el.style.cssText = value === null || value === undefined ? "" : String(value);
    } else if (BOOLEAN_ATTRS.has(name)) {
      el.toggleAttribute(name, !!value);
    } else if (name.startsWith("aria-") || name.startsWith("data-")) {
      if (value === null || value === undefined) el.removeAttribute(name);
      else el.setAttribute(name, String(value));
    } else if (value === null || value === undefined || typeof value === "boolean" || typeof value === "function") {
      el.removeAttribute(name);
    } else {
      el.setAttribute(name, String(value));
    }
  }

  // The same rule React uses: leave the DOM alone when the value already matches, which is what keeps the
  // caret where it is. A number input compares loosely, so typing "1." is not rewritten to "1".
  function writeValue(el) {
    const want = el.__dcValue;
    if (el.type === "number") {
      if ((want === 0 && el.value === "") || el.value != want) el.value = want; // eslint-disable-line eqeqeq
    } else if (el.value !== want) {
      el.value = want;
    }
  }

  function patchElement(el, vnode) {
    const prev = el.__dcAttrs || {};
    const next = {};
    let hasValue = false;
    for (const [name, value] of vnode.attrs) {
      next[name] = value;
      if (EVENTS[name]) {
        bindEvent(el, name, value);
      } else if (name === "value" && CONTROLLED.has(el.tagName)) {
        el.__dcValue = value === null || value === undefined ? "" : String(value);
        // React mirrors the value into the default too. Neither write touches what a person has typed.
        el.defaultValue = el.__dcValue;
        hasValue = true;
      } else if (prev[name] !== value) {
        setAttr(el, name, value);
      }
    }
    el.__dcAttrs = next;
    patchChildren(el, vnode.kids);
    // After the children, because a select can only take a value once its options exist.
    if (hasValue) writeValue(el);
  }

  function bindEvent(el, attr, handler) {
    const handlers = el.__dcHandlers || (el.__dcHandlers = {});
    // React's onChange fires on every keystroke in a text field, which is the browser's input event.
    const type = attr === "onchange" && el.tagName !== "SELECT" ? "input" : EVENTS[attr];
    if (!(type in handlers)) {
      el.addEventListener(type, (event) => {
        if (handlers[type]) handlers[type](event);
      });
    }
    handlers[type] = typeof handler === "function" ? handler : null;
  }

  function patchChildren(parent, vkids) {
    const old = parent.__dcKids || new Map();
    const next = new Map();
    for (const vnode of vkids) {
      const id = (vnode.tag || "#text") + "|" + vnode.key;
      next.set(id, old.get(id) || (vnode.tag ? document.createElement(vnode.tag) : document.createTextNode("")));
    }
    old.forEach((node, id) => {
      if (!next.has(id)) node.remove();
    });
    let cursor = parent.firstChild;
    vkids.forEach((vnode) => {
      const node = next.get((vnode.tag || "#text") + "|" + vnode.key);
      if (vnode.tag) patchElement(node, vnode);
      else if (node.nodeValue !== vnode.text) node.nodeValue = vnode.text;
      // Positions are structural, so nodes only ever get inserted here. Moving one would blur its focus.
      if (node === cursor) cursor = cursor.nextSibling;
      else parent.insertBefore(node, cursor);
    });
    parent.__dcKids = next;
  }

  class DCLogic {
    constructor(props) {
      this.props = props || {};
      this.state = {};
    }
    // State merges at once and the render is batched, so a handler can read back what it just set.
    setState(update) {
      const patch = typeof update === "function" ? update(this.state) : update;
      this.state = Object.assign({}, this.state, patch);
      if (this.__schedule) this.__schedule();
    }
    componentDidMount() {}
    componentWillUnmount() {}
    renderVals() { return {}; }
  }

  /** Splits a .dc.html source into its template, logic and prop declarations, without running anything. */
  function parse(source) {
    const open = /<x-dc(?:\s[^>]*)?>/.exec(source);
    const end = source.lastIndexOf("</x-dc>");
    if (!open || end < open.index) throw new Error("dc-lite: no <x-dc> block in this file");
    const doc = new DOMParser().parseFromString(source, "text/html");
    const script = doc.querySelector("script[data-dc-script]");
    if (!script) throw new Error("dc-lite: no <script data-dc-script> in this file");
    return {
      template: source.slice(open.index + open[0].length, end),
      js: script.textContent,
      props: JSON.parse(script.getAttribute("data-props") || "{}"),
      title: doc.title
    };
  }

  function compile(def) {
    if (def.compiled) return def.compiled;
    const holder = document.createElement("template");
    holder.innerHTML = def.template.replace(RAW_TAGS, (match, bracket, tag) => bracket + RAW_PREFIX + tag);
    def.helmet = Array.from(holder.content.querySelectorAll("helmet > *"));
    def.compiled = compileChildren(holder.content);
    return def.compiled;
  }

  function installHelmet(def) {
    if (def.helmetInstalled) return;
    def.helmetInstalled = true;
    def.helmet.forEach((node) => document.head.appendChild(document.importNode(node, true)));
  }

  function defaultProps(def) {
    const props = {};
    Object.keys(def.props).forEach((name) => {
      if (def.props[name] && def.props[name].default !== undefined) props[name] = def.props[name].default;
    });
    return props;
  }

  /** Mounts a parsed definition into container. onRender runs after every render with the logic instance. */
  function mount(def, container, props, onRender) {
    const fns = compile(def);
    installHelmet(def);
    const Component = new Function("DCLogic", def.js + "\n;return typeof Component !== 'undefined' ? Component : undefined;")(DCLogic);
    if (typeof Component !== "function") throw new Error("dc-lite: the script must define class Component extends DCLogic");
    const allProps = Object.assign(defaultProps(def), props);
    const logic = new Component(allProps);
    const host = document.createElement("div");
    host.className = "sc-host";
    container.appendChild(host);

    let queued = false;
    let unmounted = false;
    function render() {
      queued = false;
      if (unmounted) return;
      const out = [];
      renderAll(fns, Object.assign({}, allProps, logic.renderVals()), out, "");
      patchChildren(host, out);
      if (onRender) onRender(logic);
    }
    logic.__schedule = () => {
      if (queued) return;
      queued = true;
      Promise.resolve().then(render);
    };

    // A controlled field shows its state, not what was typed: restore it once any handler has run.
    function restoreControlled(event) {
      const el = event.target;
      if (el.__dcValue !== undefined) Promise.resolve().then(() => Promise.resolve()).then(() => writeValue(el));
    }
    host.addEventListener("input", restoreControlled);
    host.addEventListener("change", restoreControlled);

    render();
    logic.componentDidMount();
    return {
      logic,
      unmount() {
        unmounted = true;
        logic.componentWillUnmount();
        host.remove();
      }
    };
  }

  global.DcLite = { parse, mount };
})(typeof window !== "undefined" ? window : this);
