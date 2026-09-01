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
    this.__root = null;
    this.rect = { left: 0, top: 0, width: 200, height: 30 };
    this.styleMap = { display: "block", visibility: "visible", opacity: "1" };
    this.disabled = false;
    this.required = false;
    this.focusCount = 0;
    this.blurCount = 0;
    this.scrollIntoViewCount = 0;
    this.clickCount = 0;
    this.textContentWrites = 0;
  }

  /**
   * Editability inherits, and `contenteditable="false"` stops it again, so this has
   * to be answered by walking rather than by reading one attribute. Form controls
   * are separated from editing surfaces by owning a `value`, not by this flag.
   */
  get isContentEditable() {
    let node = this;
    while (node) {
      const raw = node.getAttribute("contenteditable");
      if (raw !== null) return ["", "true", "plaintext-only"].includes(raw.toLowerCase());
      node = node.parentElement;
    }
    return false;
  }

  /** What `execCommand("insertText")` does to a plain editable element. */
  __insertText(text, replacesSelection) {
    if (replacesSelection) {
      this._childNodes = [];
      this._text = text;
    } else {
      this._text = `${this._text}${text}`;
    }
  }

  get children() {
    return this._childNodes.filter((node) => node instanceof StubHTMLElement);
  }

  appendChild(node) {
    node.parentElement = this;
    node.ownerDocument = this.ownerDocument;
    if (node.__root === null) node.__root = this.__root;
    this._childNodes.push(node);
    return node;
  }

  getRootNode() {
    return this.__root;
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

  set textContent(next) {
    this.textContentWrites += 1;
    this._childNodes = [];
    this._text = next == null ? "" : String(next);
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

  // Both take a selector list, exactly as querySelectorAll below does. Matching the
  // raw string instead quietly answers "no" to every comma-separated question.
  matches(selector) {
    return splitSelector(selector).some((part) => matchesSelector(this, part));
  }

  closest(selector) {
    let node = this;
    while (node) {
      if (node.matches(selector)) return node;
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
 * Simulates Quill, ProseMirror, TipTap, Lexical or Draft.js.
 *
 * All of them keep their own document model and treat the DOM as a projection of
 * it. Assigning textContent updates only the projection, and the editor's next
 * render paints the model straight back over it, so that write silently loses --
 * the field looks filled for an instant and is empty by the time anyone checks.
 * `execCommand("insertText")` raises the real beforeinput they listen for, which
 * is why it is the one write all of them accept. Modelling that here is the whole
 * reason this stub can tell a correct fill from a plausible-looking one.
 */
const installRichTextEditor = (node) => {
  let model = node._text || "";
  Object.defineProperty(node, "textContent", {
    configurable: true,
    get: () => model,
    set: () => {
      node.textContentWrites += 1;
    },
  });
  Object.defineProperty(node, "innerText", { configurable: true, get: () => model });
  node.__insertText = (text, replacesSelection) => {
    model = replacesSelection ? text : `${model}${text}`;
  };
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

const createElement = (spec, document, root = document) => {
  const tag = String(spec.tag || "div").toLowerCase();
  let element;
  if (tag === "select") element = new StubHTMLSelectElement(tag);
  else if (tag === "textarea") element = new StubHTMLTextAreaElement(tag);
  else if (tag === "input") element = new StubHTMLInputElement(tag);
  else if (tag === "option") element = new StubHTMLOptionElement();
  else if (tag === "a") element = new StubHTMLAnchorElement(tag);
  else element = new StubHTMLElement(tag);

  element.ownerDocument = document;
  element.__root = root;
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
      option.__root = root;
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

  for (const childSpec of spec.children || []) element.appendChild(createElement(childSpec, document, root));

  // `frame: {elements: [...]}` on an iframe spec gives it a same-origin document of
  // its own, and `shadow: [...]` on any element opens a shadow root under it. Both
  // are roots the top document's querySelector cannot see into, which is the whole
  // reason the discovery script walks rather than sweeps.
  if (spec.frame) {
    element.contentDocument = buildRoot(spec.frame, {
      kind: "document",
      origin: document.__origin,
      host: element,
    });
  }
  if (spec.shadow) {
    element.shadowRoot = buildRoot({ elements: spec.shadow }, {
      kind: "shadow",
      document,
      host: element,
    });
  }

  if (spec.richTextEditor) installRichTextEditor(element);

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

const computedStyleOf = (element) => ({ ...element.styleMap });

/**
 * Selection is per-document in a real browser, which is exactly why the fill
 * script reaches for it through the element's own view rather than through the
 * top window.
 */
const makeView = (root) => ({
  getComputedStyle: computedStyleOf,
  getSelection: () => root.__selection,
});

/**
 * Build a queryable root and fill it from `spec.elements`.
 *
 * `options.kind` is "document" for the page and for each frame's own document, and
 * "shadow" for an open shadow root. A shadow root is a DocumentFragment: it answers
 * querySelector and getElementById, and it is what getRootNode returns for the
 * elements inside it, but it is not their ownerDocument, which stays the containing
 * document.
 */
const buildRoot = (spec, options) => {
  const isShadow = options.kind === "shadow";
  const root = isShadow
    ? { host: options.host, __shadow: true }
    : { title: spec.title || "", activeElement: null, forms: [], __origin: options.origin };
  const document = isShadow ? options.document : root;
  root.__host = options.host || null;
  if (!isShadow) {
    // Injected scripts reach getComputedStyle through the element's own view, so a
    // frame document with no defaultView silently falls back to the top window and
    // reads the wrong styles. Every document here has one.
    root.defaultView = makeView(root);
    root.__selection = {
      __range: null,
      removeAllRanges() {
        this.__range = null;
      },
      addRange(range) {
        this.__range = range;
      },
    };
    root.createRange = () => ({
      __node: null,
      selectNodeContents(node) {
        this.__node = node;
      },
    });
    // Only insertText is modelled, because it is the only command the fill script
    // issues. `spec.execCommandFails` is how a test asks for the browser that
    // refuses, so the script's fallback is exercised rather than assumed.
    root.execCommand = (command, showUI, value) => {
      if (spec.execCommandFails || command !== "insertText") return false;
      const target = root.activeElement;
      if (!target || target.isContentEditable !== true) return false;
      const range = root.__selection.__range;
      // A real insertion replaces the selection. Whether the script selected the
      // node's contents first is the difference between replacing a pre-filled
      // draft and appending the answer to the end of it.
      target.__insertText(String(value == null ? "" : value), Boolean(range) && range.__node === target);
      return true;
    };
  }

  const body = new StubHTMLElement(isShadow ? "shadow-root" : "body");
  body.ownerDocument = document;
  body.__root = root;
  root.__body = body;
  if (!isShadow) {
    root.body = body;
    root.documentElement = body;
  }
  for (const childSpec of spec.elements || []) body.appendChild(createElement(childSpec, document, root));

  root.querySelectorAll = (selector) => body.querySelectorAll(selector);
  root.querySelector = (selector) => body.querySelector(selector);
  root.getElementById = (id) => body.querySelector(`#${id}`);
  if (!isShadow) {
    root.forms = body.querySelectorAll("form");
    root.elementFromPoint = (x, y) => hitTest(body, x, y);
  }
  return root;
};

/** Every root reachable from `document`, outermost first, the way discovery walks. */
const reachableRoots = (document) => {
  const roots = [];
  const queue = [document];
  while (queue.length > 0) {
    const root = queue.shift();
    if (roots.includes(root)) continue;
    roots.push(root);
    for (const element of descendants(root.__body)) {
      if (element.contentDocument) queue.push(element.contentDocument);
      if (element.shadowRoot) queue.push(element.shadowRoot);
    }
  }
  return roots;
};

/** How a test names the root a control was found in: "document", "frame:#id", "shadow:#id". */
const rootLabel = (root, document) => {
  if (root === document) return "document";
  const host = root.__host ? root.__host.getAttribute("id") : null;
  return `${root.__shadow ? "shadow" : "frame"}:${host ? `#${host}` : "?"}`;
};

export const buildDom = (spec) => {
  const document = buildRoot(spec, {
    kind: "document",
    origin: spec.origin || "https://jobs.example.com",
  });
  const body = document.__body;

  const window = {
    innerWidth: (spec.viewport || {}).width ?? 1280,
    innerHeight: (spec.viewport || {}).height ?? 800,
    HTMLInputElement: StubHTMLInputElement,
    HTMLTextAreaElement: StubHTMLTextAreaElement,
    HTMLSelectElement: StubHTMLSelectElement,
    HTMLAnchorElement: StubHTMLAnchorElement,
    getComputedStyle: computedStyleOf,
    getSelection: () => document.__selection,
  };

  const location = { origin: document.__origin, href: document.__origin + (spec.path || "/") };

  const snapshot = () =>
    reachableRoots(document)
      .flatMap((root) => descendants(root.__body).map((element) => ({ element, root })))
      .filter(
        ({ element }) =>
          ["input", "textarea", "select"].includes(element.tagName.toLowerCase()) ||
          (element.isContentEditable === true && !("value" in element)),
      )
      .map(({ element, root }) => ({
        root: rootLabel(root, document),
        id: element.getAttribute("id"),
        name: element.getAttribute("name"),
        tag: element.tagName.toLowerCase(),
        type: (element.getAttribute("type") || "").toLowerCase(),
        value: element.value === undefined ? null : String(element.value),
        checked: element.checked === undefined ? null : Boolean(element.checked),
        selected_labels: (element.options || [])
          .filter((option) => option.selected === true)
          .map((option) => option.textContent),
        text: element.innerText,
        editable: element.isContentEditable === true,
        text_content_writes: element.textContentWrites ?? 0,
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
