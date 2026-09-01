/**
 * A small but faithful DOM stub used to execute the REAL JavaScript that the
 * Python worker injects into portal pages (see
 * applyocalypse_automation/browser/field_detection.py).
 *
 * The important part is that `value` / `checked` live on the *prototype* of the
 * element classes, exactly like the browser, and that `installReactTracker`
 * reproduces React's `inputValueTracking` implementation: React defines an
 * OWN property on the node whose setter updates React's cached copy before
 * delegating to the native prototype setter. A plain `node.value = x` therefore
 * keeps React's cache in sync and React's `updateValueIfChanged` reports "no
 * change", which is why React discards the synthetic change event.
 *
 * A write only registers with React if it goes through the prototype setter
 * captured via Object.getOwnPropertyDescriptor(...).set.
 */

const VOID_TAGS = new Set(["input", "br", "img", "hr", "meta", "link"]);

class StubEvent {
  constructor(type, init = {}) {
    this.type = type;
    this.bubbles = Boolean(init.bubbles);
    this.target = null;
  }
}

class StubHTMLElement {
  constructor(tag) {
    this.tagName = String(tag).toUpperCase();
    this._attrs = {};
    this._listeners = {};
    this._childNodes = [];
    this._text = "";
    this.parentElement = null;
    this.ownerDocument = null;
    this.rect = { left: 0, top: 0, width: 200, height: 30 };
    this.styleMap = { display: "block", visibility: "visible", opacity: "1" };
    this.disabled = false;
    this.required = false;
    this.focusCount = 0;
    this.blurCount = 0;
    this.scrollIntoViewCount = 0;
    this.clickCount = 0;
  }

  get children() {
    return this._childNodes.filter((node) => node instanceof StubHTMLElement);
  }

  appendChild(node) {
    node.parentElement = this;
    node.ownerDocument = this.ownerDocument;
    this._childNodes.push(node);
    return node;
  }

  getAttribute(name) {
    const value = this._attrs[name];
    return value === undefined ? null : String(value);
  }

  setAttribute(name, value) {
    this._attrs[name] = String(value);
  }

  hasAttribute(name) {
    return this._attrs[name] !== undefined;
  }

  addEventListener(type, handler) {
    if (!this._listeners[type]) this._listeners[type] = [];
    this._listeners[type].push(handler);
  }

  dispatchEvent(event) {
    event.target = this;
    let node = this;
    while (node) {
      const handlers = node._listeners[event.type] || [];
      for (const handler of handlers.slice()) handler.call(node, event);
      node = event.bubbles ? node.parentElement : null;
    }
    return true;
  }

  focus() {
    this.focusCount += 1;
    if (this.ownerDocument) this.ownerDocument.activeElement = this;
  }

  blur() {
    this.blurCount += 1;
    if (this.ownerDocument && this.ownerDocument.activeElement === this) {
      this.ownerDocument.activeElement = null;
    }
  }

  get textContent() {
    const own = this._text || "";
    const nested = this.children.map((child) => child.textContent).join(" ");
    return [own, nested].filter(Boolean).join(" ").replace(/\s+/g, " ").trim();
  }

  get innerText() {
    return this.textContent;
  }

  getBoundingClientRect() {
    const { left, top, width, height } = this.rect;
    return { x: left, y: top, left, top, width, height, right: left + width, bottom: top + height };
  }

  scrollIntoView() {
    this.scrollIntoViewCount += 1;
  }

  click() {
    this.clickCount += 1;
    this.dispatchEvent(new StubEvent("click", { bubbles: true }));
  }

  contains(other) {
    let node = other;
    while (node) {
      if (node === this) return true;
      node = node.parentElement;
    }
    return false;
  }

  matches(selector) {
    return matchesSelector(this, selector);
  }

  closest(selector) {
    let node = this;
    while (node) {
      if (matchesSelector(node, selector)) return node;
      node = node.parentElement;
    }
    return null;
  }

  querySelector(selector) {
    return this.querySelectorAll(selector)[0] || null;
  }

  querySelectorAll(selector) {
    // Document order across every comma-separated part, exactly like the real DOM.
    const parts = splitSelector(selector);
    if (parts.length === 0) return [];
    return descendants(this).filter((node) => parts.some((part) => matchesSelector(node, part)));
  }

  get form() {
    return this.closest("form");
  }
}

class StubHTMLInputElement extends StubHTMLElement {
  constructor(tag) {
    super(tag);
    this._value = "";
    this._checked = false;
    this.nativeValueWrites = 0;
    this.nativeCheckedWrites = 0;
  }

  get value() {
    return this._value;
  }

  set value(next) {
    this._value = String(next == null ? "" : next);
    this.nativeValueWrites += 1;
  }

  get checked() {
    return this._checked;
  }

  set checked(next) {
    this._checked = Boolean(next);
    this.nativeCheckedWrites += 1;
  }
}

class StubHTMLTextAreaElement extends StubHTMLInputElement {}

/**
 * `href` on a real anchor is resolved against the document, so a relative link
 * comes back absolute. `isExternalLink` in the click script compares that
 * against `location.origin`, and would wave every relative link through if the
 * stub handed back the raw attribute.
 */
class StubHTMLAnchorElement extends StubHTMLElement {
  get href() {
    const raw = this.getAttribute("href");
    if (raw === null) return "";
    if (/^[a-z][a-z0-9+.-]*:/i.test(raw) || raw.startsWith("#")) return raw;
    const origin = (this.ownerDocument && this.ownerDocument.__origin) || "";
    return raw.startsWith("/") ? origin + raw : origin + "/" + raw;
  }
}

class StubHTMLOptionElement extends StubHTMLElement {
  constructor() {
    super("option");
    this.selected = false;
    this.disabled = false;
  }

  get value() {
    const attribute = this.getAttribute("value");
    return attribute === null ? this.textContent : attribute;
  }
}

class StubHTMLSelectElement extends StubHTMLElement {
  constructor(tag) {
    super(tag);
    this.options = [];
    this.nativeValueWrites = 0;
  }

  get value() {
    const selected = this.options.find((option) => option.selected === true);
    return selected ? selected.value : "";
  }

  set value(next) {
    this.nativeValueWrites += 1;
    const wanted = String(next == null ? "" : next);
    let matched = false;
    for (const option of this.options) {
      const isMatch = !matched && option.value === wanted;
      option.selected = isMatch;
      if (isMatch) matched = true;
    }
  }
}

const isPaintedAt = (element, x, y) => {
  const style = element.styleMap;
  if (style.display === "none" || style.visibility === "hidden") return false;
  const { left, top, width, height } = element.rect;
  if (width <= 0 || height <= 0) return false;
  return x >= left && x <= left + width && y >= top && y <= top + height;
};

const stackingOrder = (element) => {
  const raw = element.styleMap["z-index"] ?? element.styleMap.zIndex;
  const parsed = Number.parseInt(raw, 10);
  return Number.isNaN(parsed) ? 0 : parsed;
};

/**
 * Topmost element covering a point: highest z-index wins, and within one layer
 * the element painted last does. Because `descendants` walks in document order,
 * "last" is also the deepest, which is what the real hit test settles on.
 */
const hitTest = (root, x, y) => {
  let winner = null;
  let winningLayer = -Infinity;
  for (const element of descendants(root)) {
    if (!isPaintedAt(element, x, y)) continue;
    const layer = stackingOrder(element);
    if (layer >= winningLayer) {
      winner = element;
      winningLayer = layer;
    }
  }
  return winner;
};

const descendants = (root) => {
  const out = [];
  const walk = (node) => {
    for (const child of node.children) {
      out.push(child);
      walk(child);
    }
  };
  walk(root);
  return out;
};

const splitSelector = (selector) =>
  String(selector)
    .split(",")
    .map((part) => part.trim())
    .filter(Boolean);

const ATTR_PATTERN = /\[([a-zA-Z0-9_:-]+)(?:=(?:"([^"]*)"|'([^']*)'|([^\]]*)))?\]/g;

const matchesSelector = (element, selector) => {
  if (!(element instanceof StubHTMLElement)) return false;
  const raw = String(selector).trim();
  if (!raw) return false;
  const attributes = [];
  let rest = raw.replace(ATTR_PATTERN, (_match, name, doubleQuoted, singleQuoted, bare) => {
    attributes.push([name, doubleQuoted ?? singleQuoted ?? bare ?? null]);
    return "";
  });
  let expectedId = null;
  rest = rest.replace(/#([A-Za-z0-9_:.-]+)/g, (_match, id) => {
    expectedId = id;
    return "";
  });
  const tag = rest.trim();
  if (tag && tag !== "*" && element.tagName.toLowerCase() !== tag.toLowerCase()) return false;
  if (expectedId !== null && element.getAttribute("id") !== expectedId) return false;
  for (const [name, expected] of attributes) {
    const actual = element.getAttribute(name);
    if (actual === null) return false;
    if (expected !== null && actual !== expected) return false;
  }
  return true;
};

/**
 * Reproduces React's ValueTracker (packages/react-dom/src/client/inputValueTracking.js).
 */
const installReactTracker = (node, property) => {
  const descriptor = Object.getOwnPropertyDescriptor(Object.getPrototypeOf(node), property);
  if (!descriptor || typeof descriptor.set !== "function") return;
  let cached = String(descriptor.get.call(node));
  Object.defineProperty(node, property, {
    configurable: true,
    enumerable: true,
    get() {
      return descriptor.get.call(this);
    },
    set(next) {
      cached = String(next);
      descriptor.set.call(this, next);
    },
  });
  node.__reactTracker = {
    property,
    changed() {
      const current = String(descriptor.get.call(node));
      if (current === cached) return false;
      cached = current;
      return true;
    },
  };
  node.__reactSawChange = null;
  const observe = () => {
    if (node.__reactSawChange === null) node.__reactSawChange = node.__reactTracker.changed();
  };
  node.addEventListener("input", observe);
  node.addEventListener("change", observe);
};

/**
 * Simulates a controlled component that refuses (or reformats) the value it was
 * given: on `change` the framework writes its own value straight back through
 * the native prototype setter, exactly as a React re-render would.
 */
const installRevertOnChange = (node, property, revertTo) => {
  const descriptor = Object.getOwnPropertyDescriptor(Object.getPrototypeOf(node), property);
  if (!descriptor || typeof descriptor.set !== "function") return;
  let reverted = false;
  node.addEventListener("change", () => {
    if (reverted) return;
    reverted = true;
    descriptor.set.call(node, revertTo);
  });
};

const createElement = (spec, document) => {
  const tag = String(spec.tag || "div").toLowerCase();
  let element;
  if (tag === "select") element = new StubHTMLSelectElement(tag);
  else if (tag === "textarea") element = new StubHTMLTextAreaElement(tag);
  else if (tag === "input") element = new StubHTMLInputElement(tag);
  else if (tag === "option") element = new StubHTMLOptionElement();
  else if (tag === "a") element = new StubHTMLAnchorElement(tag);
  else element = new StubHTMLElement(tag);

  element.ownerDocument = document;
  element._attrs = { ...(spec.attrs || {}) };
  element._text = spec.text || "";
  if (spec.rect) element.rect = { ...element.rect, ...spec.rect };
  if (spec.style) element.styleMap = { ...element.styleMap, ...spec.style };
  if (spec.required) element.required = true;
  if (spec.disabled) element.disabled = true;

  if (tag === "select") {
    for (const optionSpec of spec.options || []) {
      const option = new StubHTMLOptionElement();
      option.ownerDocument = document;
      option._text = optionSpec.label == null ? "" : String(optionSpec.label);
      if (optionSpec.value !== undefined && optionSpec.value !== null) {
        option.setAttribute("value", String(optionSpec.value));
      }
      option.selected = Boolean(optionSpec.selected);
      option.disabled = Boolean(optionSpec.disabled);
      element.appendChild(option);
      element.options.push(option);
    }
  }
  if (spec.value !== undefined && element instanceof StubHTMLInputElement) element._value = String(spec.value);
  if (spec.value !== undefined && element instanceof StubHTMLSelectElement) element.value = String(spec.value);
  if (spec.checked !== undefined && element instanceof StubHTMLInputElement) element._checked = Boolean(spec.checked);

  for (const childSpec of spec.children || []) element.appendChild(createElement(childSpec, document));

  if (spec.react) {
    const type = (element.getAttribute("type") || "").toLowerCase();
    installReactTracker(element, type === "checkbox" || type === "radio" ? "checked" : "value");
  }
  // Installed after the tracker so the tracker still observes the write first.
  if (spec.revertOnChange !== undefined) installRevertOnChange(element, "value", String(spec.revertOnChange));
  if (spec.revertCheckedOnChange !== undefined) {
    installRevertOnChange(element, "checked", Boolean(spec.revertCheckedOnChange));
  }
  return element;
};

export const buildDom = (spec) => {
  const document = {
    title: spec.title || "",
    activeElement: null,
    forms: [],
    __origin: spec.origin || "https://jobs.example.com",
  };
  const body = new StubHTMLElement("body");
  body.ownerDocument = document;
  document.body = body;
  document.documentElement = body;
  for (const childSpec of spec.elements || []) body.appendChild(createElement(childSpec, document));

  document.querySelectorAll = (selector) => body.querySelectorAll(selector);
  document.querySelector = (selector) => body.querySelector(selector);
  document.getElementById = (id) => body.querySelector(`#${id}`);
  document.forms = body.querySelectorAll("form");
  document.elementFromPoint = (x, y) => hitTest(body, x, y);

  const window = {
    innerWidth: (spec.viewport || {}).width ?? 1280,
    innerHeight: (spec.viewport || {}).height ?? 800,
    HTMLInputElement: StubHTMLInputElement,
    HTMLTextAreaElement: StubHTMLTextAreaElement,
    HTMLSelectElement: StubHTMLSelectElement,
    HTMLAnchorElement: StubHTMLAnchorElement,
    getComputedStyle: (element) => ({ ...element.styleMap }),
  };

  const location = { origin: document.__origin, href: document.__origin + (spec.path || "/") };

  const snapshot = () =>
    descendants(body)
      .filter((element) => ["input", "textarea", "select"].includes(element.tagName.toLowerCase()))
      .map((element) => ({
        id: element.getAttribute("id"),
        name: element.getAttribute("name"),
        tag: element.tagName.toLowerCase(),
        type: (element.getAttribute("type") || "").toLowerCase(),
        value: element.value === undefined ? null : String(element.value),
        checked: element.checked === undefined ? null : Boolean(element.checked),
        selected_labels: (element.options || [])
          .filter((option) => option.selected === true)
          .map((option) => option.textContent),
        native_value_writes: element.nativeValueWrites ?? 0,
        native_checked_writes: element.nativeCheckedWrites ?? 0,
        focus_count: element.focusCount,
        blur_count: element.blurCount,
        react_tracked: Boolean(element.__reactTracker),
        react_saw_change: element.__reactSawChange === undefined ? null : element.__reactSawChange,
      }));

  return {
    window,
    document,
    location,
    CSS: { escape: (value) => String(value) },
    Event: StubEvent,
    snapshot,
  };
};
