import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

/**
 * Executes the REAL DOM_BLOCKER_DISCOVERY_SCRIPT embedded in the Python worker
 * against a faithful DOM stub. Locks in the fix for the production bug where an
 * invisible reCAPTCHA v3 badge (present on nearly every ATS application form)
 * was flagged as a CAPTCHA and hung the run in an endless pause/resume loop.
 */

const FIELD_DETECTION = resolve(
  __dirname,
  "..",
  "services",
  "automation-python",
  "applyocalypse_automation",
  "browser",
  "field_detection.py"
);

const extractBlockerScript = (): string => {
  const py = readFileSync(FIELD_DETECTION, "utf8");
  const marker = 'DOM_BLOCKER_DISCOVERY_SCRIPT = r"""';
  const start = py.indexOf(marker);
  if (start === -1) throw new Error("DOM_BLOCKER_DISCOVERY_SCRIPT not found");
  const bodyStart = start + marker.length;
  const end = py.indexOf('"""', bodyStart);
  return py.slice(bodyStart, end).trim();
};

type Rect = { width: number; height: number };
type Style = { visibility?: string; display?: string; opacity?: string };

class StubElement {
  tag: string;
  id: string | null;
  classes: string[];
  attrs: Record<string, string>;
  rect: Rect;
  style: Required<Style>;
  parent: StubElement | null;

  constructor(init: {
    tag: string;
    id?: string | null;
    classes?: string[];
    attrs?: Record<string, string>;
    rect?: Rect;
    style?: Style;
    parent?: StubElement | null;
  }) {
    this.tag = init.tag;
    this.id = init.id ?? null;
    this.classes = init.classes ?? [];
    this.attrs = init.attrs ?? {};
    this.rect = init.rect ?? { width: 300, height: 80 };
    this.style = { visibility: "visible", display: "block", opacity: "1", ...init.style };
    this.parent = init.parent ?? null;
  }

  getAttribute(name: string): string | null {
    return name in this.attrs ? this.attrs[name] : null;
  }

  getBoundingClientRect(): Rect {
    return this.rect;
  }

  closest(selector: string): StubElement | null {
    const want = selector.replace(".", "");
    // Real closest() considers the element itself before walking up.
    if (this.classes.includes(want)) return this;
    let cur: StubElement | null = this.parent;
    while (cur) {
      if (cur.classes.includes(want)) return cur;
      cur = cur.parent;
    }
    return null;
  }
}

const matchOne = (el: StubElement, selectorRaw: string): boolean => {
  const selector = selectorRaw.trim();
  let m: RegExpMatchArray | null;
  if ((m = selector.match(/^(\w+)\[(\S+?)\*="([^"]+)"\s*i\]$/))) {
    const [, tag, attr, val] = m;
    if (el.tag !== tag) return false;
    return (el.getAttribute(attr) ?? "").toLowerCase().includes(val.toLowerCase());
  }
  if ((m = selector.match(/^(\w+)\.([\w-]+)$/))) return el.tag === m[1] && el.classes.includes(m[2]);
  if ((m = selector.match(/^\.([\w-]+)$/))) return el.classes.includes(m[1]);
  if ((m = selector.match(/^#([\w-]+)$/))) return el.id === m[1];
  if ((m = selector.match(/^(\w+)\[(\S+?)="([^"]+)"\]$/))) return el.tag === m[1] && el.getAttribute(m[2]) === m[3];
  if ((m = selector.match(/^\[([\w-]+)\]$/))) return el.getAttribute(m[1]) !== null;
  if ((m = selector.match(/^(\w+)$/))) return el.tag === m[1];
  throw new Error(`unhandled selector: ${selector}`);
};

type Fixture = { title?: string; text?: string; html?: string; elements: StubElement[] };

const runDetection = (script: string, fixture: Fixture): Array<Record<string, unknown>> => {
  const qsa = (selector: string): StubElement[] => {
    const parts = selector.split(",").map((s) => s.trim());
    return fixture.elements.filter((el) => parts.some((p) => matchOne(el, p)));
  };
  const documentStub = {
    title: fixture.title ?? "",
    body: { innerText: fixture.text ?? "" },
    documentElement: { innerHTML: fixture.html ?? "" },
    querySelector: (s: string) => qsa(s)[0] ?? null,
    querySelectorAll: qsa
  };
  const windowStub = { getComputedStyle: (el: StubElement) => el.style };
  const fn = new Function("document", "window", `return ${script}`);
  return JSON.parse(fn(documentStub, windowStub));
};

const captchaVendor = (blockers: Array<Record<string, unknown>>): string | null => {
  const captcha = blockers.find((b) => b.blocker_type === "CAPTCHA");
  if (!captcha) return null;
  const metadata = captcha.metadata as { vendor?: string } | undefined;
  return metadata?.vendor ?? "unknown";
};

const badge = new StubElement({ tag: "div", classes: ["grecaptcha-badge"], rect: { width: 70, height: 60 } });

const FIXTURES: Record<string, { fixture: Fixture; expected: string | null }> = {
  clean_application_form: {
    fixture: {
      text: "first name last name email upload resume submit application",
      html: '<form><input name="email"></form>',
      elements: [new StubElement({ tag: "input", attrs: { name: "email" } })]
    },
    expected: null
  },
  invisible_recaptcha_v3_badge: {
    fixture: {
      text: "this site is protected by recaptcha and the google privacy policy apply now",
      html: '<div class="grecaptcha-badge"><iframe src="recaptcha/api2/anchor?size=invisible"></iframe></div>',
      elements: [
        badge,
        new StubElement({
          tag: "iframe",
          attrs: { src: "https://www.google.com/recaptcha/api2/anchor?k=abc&size=invisible" },
          rect: { width: 1, height: 1 },
          parent: badge
        })
      ]
    },
    expected: null
  },
  visible_recaptcha_v2_checkbox: {
    fixture: {
      text: "i'm not a robot",
      html: "",
      elements: [
        new StubElement({
          tag: "iframe",
          attrs: { src: "https://www.google.com/recaptcha/api2/anchor?k=abc" },
          rect: { width: 304, height: 78 }
        })
      ]
    },
    expected: "recaptcha"
  },
  visible_recaptcha_image_challenge: {
    fixture: {
      text: "select all images with traffic lights",
      html: "",
      elements: [
        new StubElement({
          tag: "iframe",
          attrs: { src: "https://www.google.com/recaptcha/api2/bframe?k=abc" },
          rect: { width: 400, height: 580 }
        })
      ]
    },
    expected: "recaptcha"
  },
  visible_hcaptcha: {
    fixture: {
      text: "verify you are human",
      html: "",
      elements: [
        new StubElement({
          tag: "iframe",
          attrs: { src: "https://newassets.hcaptcha.com/captcha/v1" },
          rect: { width: 303, height: 78 }
        })
      ]
    },
    expected: "hcaptcha"
  },
  cloudflare_interstitial: {
    fixture: {
      title: "Just a moment...",
      text: "checking your browser before accessing",
      html: '<div id="challenge-form"></div>',
      elements: [new StubElement({ tag: "div", id: "challenge-form", rect: { width: 500, height: 300 } })]
    },
    expected: "cloudflare"
  },
  cloudflare_turnstile: {
    fixture: {
      text: "",
      html: "",
      elements: [
        new StubElement({
          tag: "iframe",
          attrs: { src: "https://challenges.cloudflare.com/turnstile" },
          rect: { width: 300, height: 65 }
        })
      ]
    },
    expected: "cloudflare"
  },
  hidden_recaptcha_display_none: {
    fixture: {
      text: "apply for this role",
      html: "",
      elements: [
        new StubElement({
          tag: "iframe",
          attrs: { src: "https://www.google.com/recaptcha/api2/anchor?k=abc" },
          rect: { width: 0, height: 0 },
          style: { display: "none" }
        })
      ]
    },
    expected: null
  }
};

describe("DOM_BLOCKER_DISCOVERY_SCRIPT captcha detection", () => {
  const script = extractBlockerScript();

  for (const [name, { fixture, expected }] of Object.entries(FIXTURES)) {
    it(`${name} -> ${expected ?? "no captcha"}`, () => {
      expect(captchaVendor(runDetection(script, fixture))).toBe(expected);
    });
  }

  it("never flags CAPTCHA from a bare page-text mention (the old false-positive)", () => {
    const fixture: Fixture = {
      text: "our hiring process does not use a captcha or recaptcha challenge",
      html: '<script src="https://www.google.com/recaptcha/api.js"></script>',
      elements: []
    };
    expect(captchaVendor(runDetection(script, fixture))).toBeNull();
  });
});
