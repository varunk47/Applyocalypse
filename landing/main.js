/* Applyocalypse landing interactions.
   Faithful port of the design's GSAP + ScrollTrigger + Lenis choreography,
   pushed a little further. Libraries are self-hosted in assets/vendor. */
(function () {
  "use strict";

  var reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  var finePointer = window.matchMedia("(pointer: fine)").matches;
  var qa = function (sel, root) {
    return Array.prototype.slice.call((root || document).querySelectorAll(sel));
  };
  var q = function (sel, root) {
    return (root || document).querySelector(sel);
  };

  /* Nothing must ever render blank: if the animation stack is missing or motion
     is reduced, show every hidden element at its resting state. */
  function ensureVisible() {
    qa("[data-reveal],[data-hero-rise],[data-hero-fade],[data-hero-win-tilt],[data-hero-win-inner]").forEach(function (el) {
      el.style.opacity = "1";
      el.style.transform = "none";
    });
    qa(".how-visual").forEach(function (el, i) {
      el.classList.toggle("is-active", i === 0);
    });
  }

  /* ---- Mobile menu (works with or without GSAP) ------------------------- */
  var nav = document.getElementById("nav");
  var burger = document.getElementById("burger");
  var navLinks = document.getElementById("nav-links");
  var closeMenu = function () {
    nav.classList.remove("is-open");
    burger.setAttribute("aria-expanded", "false");
  };
  burger.addEventListener("click", function () {
    var open = nav.classList.toggle("is-open");
    burger.setAttribute("aria-expanded", open ? "true" : "false");
  });
  window.addEventListener("resize", function () {
    if (window.innerWidth > 900) {
      closeMenu();
    }
  });

  /* Sticky-nav condense uses the raw scroll position, so it works even when
     Lenis is off (reduced motion). */
  var onNativeScroll = function () {
    nav.classList.toggle("is-stuck", window.scrollY > 24);
  };
  window.addEventListener("scroll", onNativeScroll, { passive: true });
  onNativeScroll();

  if (reduceMotion || !window.gsap || !window.ScrollTrigger || !window.Lenis) {
    ensureVisible();
    // Native anchor scroll + native <details> still give a full experience.
    navLinks.addEventListener("click", function (e) {
      if (e.target.closest("a")) {
        closeMenu();
      }
    });
    return;
  }

  var gsap = window.gsap;
  var ST = window.ScrollTrigger;
  gsap.registerPlugin(ST);

  /* ---- Lenis smooth scroll (driven by the GSAP ticker) ------------------ */
  var lenis = new window.Lenis({ lerp: 0.1, smoothWheel: true, wheelMultiplier: 1 });
  window.__apoLenis = lenis;
  lenis.on("scroll", ST.update);
  gsap.ticker.add(function (t) {
    lenis.raf(t * 1000);
  });
  gsap.ticker.lagSmoothing(0);

  /* Smooth-scroll the nav anchors and close the mobile menu. */
  qa("[data-nav-link]").forEach(function (a) {
    a.addEventListener("click", function (e) {
      e.preventDefault();
      var el = document.getElementById(a.getAttribute("data-nav-link"));
      if (el) {
        lenis.scrollTo(el, { offset: -68, duration: 1.15 });
      }
      closeMenu();
    });
  });

  /* ---- Hero intro: masked line rise + staggered fade -------------------- */
  (function heroIntro() {
    var rises = qa("[data-hero-rise]");
    var fades = qa("[data-hero-fade]");
    gsap.set(rises, { yPercent: 115 });
    gsap.set(fades, { opacity: 0, y: 16 });
    var tl = gsap.timeline({ defaults: { ease: "power4.out" } });
    tl.to(rises, { yPercent: 0, duration: 1.15, stagger: 0.11 }, 0.15)
      .to(fades, { opacity: 1, y: 0, duration: 0.9, stagger: 0.09 }, 0.5);
  })();

  /* ---- Hero window: intro fade, scroll de-tilt, mouse parallax ---------- */
  (function heroWindow() {
    var tilt = q("[data-hero-win-tilt]");
    var inner = q("[data-hero-win-inner]");
    var hero = q(".hero");
    if (!tilt) {
      return;
    }
    gsap.set(tilt, { willChange: "transform" });
    gsap.from(tilt, { opacity: 0, duration: 1.1, ease: "power3.out", delay: 0.55 });
    gsap.fromTo(
      tilt,
      { rotateX: 17, scale: 0.93, y: 34 },
      {
        rotateX: 0, scale: 1, y: 0, ease: "none",
        scrollTrigger: { trigger: hero, start: "top top", end: "bottom 55%", scrub: 0.5 }
      }
    );
    if (inner && hero && finePointer) {
      hero.addEventListener("pointermove", function (e) {
        var r = hero.getBoundingClientRect();
        var px = (e.clientX - r.left) / r.width - 0.5;
        var py = (e.clientY - r.top) / r.height - 0.5;
        gsap.to(inner, { rotateY: px * 7, rotateX: -py * 5, duration: 0.6, ease: "power2.out" });
      });
      hero.addEventListener("pointerleave", function () {
        gsap.to(inner, { rotateY: 0, rotateX: 0, duration: 0.9, ease: "power2.out" });
      });
    }
  })();

  /* ---- Top scroll-progress bar ------------------------------------------ */
  (function progress() {
    var bar = q("[data-progress]");
    if (bar) {
      gsap.to(bar, {
        scaleX: 1, ease: "none",
        scrollTrigger: { trigger: document.body, start: "top top", end: "bottom bottom", scrub: 0.3 }
      });
    }
  })();

  /* ---- Marquee ---------------------------------------------------------- */
  (function marquee() {
    var track = q("[data-marquee-track]");
    if (track) {
      gsap.to(track, { xPercent: -50, repeat: -1, duration: 30, ease: "none" });
    }
  })();

  /* ---- Problem statement: word-by-word ink fill on scroll --------------- */
  (function problemWords() {
    var host = q("[data-split-words]");
    if (!host) {
      return;
    }
    var raw = host.textContent.replace(/\s+/g, " ").trim();
    host.textContent = "";
    var words = raw.split(" ").map(function (w) {
      var s = document.createElement("span");
      s.className = "word";
      s.textContent = w + " ";
      host.appendChild(s);
      return s;
    });
    gsap.to(words, {
      color: "#201D17",
      stagger: 1,
      ease: "none",
      scrollTrigger: { trigger: host, start: "top 82%", end: "bottom 58%", scrub: 0.4 }
    });
  })();

  /* ---- Generic reveals -------------------------------------------------- */
  (function reveals() {
    qa("[data-reveal]").forEach(function (el) {
      var stagger = el.getAttribute("data-reveal") === "stagger";
      var targets = stagger ? el.children : el;
      gsap.set(targets, { opacity: 0, y: 26 });
      var done = false;
      var run = function () {
        if (done) {
          return;
        }
        done = true;
        gsap.to(targets, { opacity: 1, y: 0, duration: 0.95, ease: "power3.out", stagger: stagger ? 0.09 : 0 });
      };
      ST.create({ trigger: el, start: "top 88%", once: true, onEnter: run });
      requestAnimationFrame(function () {
        if (el.getBoundingClientRect().top < window.innerHeight * 0.92) {
          run();
        }
      });
    });
  })();

  /* ---- How it works: scrolly step switch + dots + seal stamp ------------ */
  (function how() {
    var cards = qa(".how-visual");
    var dots = qa("[data-how-dot]");
    var panels = qa(".how-step");
    if (!cards.length || !panels.length) {
      return;
    }
    var setActive = function (idx) {
      cards.forEach(function (c, j) {
        c.classList.toggle("is-active", j === idx);
      });
      dots.forEach(function (d, j) {
        d.classList.toggle("on", j <= idx);
      });
      panels.forEach(function (p, j) {
        p.classList.toggle("active", j === idx);
      });
    };
    setActive(0);
    panels.forEach(function (panel, i) {
      ST.create({
        trigger: panel, start: "top 55%", end: "bottom 55%",
        onToggle: function (self) {
          if (self.isActive) {
            setActive(i);
          }
        }
      });
    });
    var seal = q("[data-sign-seal]");
    if (seal) {
      var last = panels[panels.length - 1];
      ST.create({
        trigger: last, start: "top 60%", once: true,
        onEnter: function () {
          gsap.fromTo(
            seal,
            { scale: 1.7, rotate: -18, opacity: 0 },
            { scale: 1, rotate: -8, opacity: 1, duration: 0.65, ease: "back.out(2)" }
          );
        }
      });
    }
  })();

  /* ---- Showcase: 3D tilt toward cursor, depth-parallax callouts, breathe - */
  (function showcase() {
    var stage = q("[data-showcase-stage]");
    var tilt = q("[data-showcase-tilt]");
    if (!stage || !tilt) {
      return;
    }
    gsap.set(tilt, { transformPerspective: 1900, transformOrigin: "50% 50%", willChange: "transform" });
    var depthEls = qa("[data-depth]", stage);
    depthEls.forEach(function (el) {
      gsap.set(el, { z: parseFloat(el.getAttribute("data-z")) || 80 });
    });
    var idleTween = null;
    var idle = function () {
      idleTween = gsap.to(tilt, { rotateX: 2, rotateY: -3, duration: 5, ease: "sine.inOut", yoyo: true, repeat: -1 });
    };
    idle();
    if (!finePointer) {
      return;
    }
    stage.addEventListener("pointerenter", function () {
      if (idleTween) {
        idleTween.kill();
      }
    });
    stage.addEventListener("pointermove", function (e) {
      var r = stage.getBoundingClientRect();
      var px = (e.clientX - r.left) / r.width - 0.5;
      var py = (e.clientY - r.top) / r.height - 0.5;
      gsap.to(tilt, { rotateY: px * 14, rotateX: -py * 11, duration: 0.5, ease: "power2.out", overwrite: "auto" });
      depthEls.forEach(function (el) {
        var d = parseFloat(el.getAttribute("data-depth")) || 20;
        gsap.to(el, { x: px * d * 1.3, y: py * d * 1.3, duration: 0.6, ease: "power2.out", overwrite: "auto" });
      });
    });
    stage.addEventListener("pointerleave", function () {
      gsap.to(tilt, {
        rotateX: 0, rotateY: 0, duration: 0.9, ease: "power3.out", overwrite: "auto",
        onComplete: idle
      });
      depthEls.forEach(function (el) {
        gsap.to(el, { x: 0, y: 0, duration: 0.9, ease: "power3.out", overwrite: "auto" });
      });
    });
  })();

  /* ---- Count-up numbers ------------------------------------------------- */
  (function counters() {
    qa("[data-count]").forEach(function (el) {
      var to = parseFloat(el.getAttribute("data-count"));
      if (!to) {
        return;
      }
      var o = { v: 0 };
      ST.create({
        trigger: el, start: "top 88%", once: true,
        onEnter: function () {
          gsap.to(o, {
            v: to, duration: 1.6, ease: "power2.out",
            onUpdate: function () {
              el.textContent = Math.round(o.v).toLocaleString();
            }
          });
        }
      });
    });
  })();

  /* ---- FAQ: smooth height animation on the native <details> ------------- */
  (function faq() {
    qa("details.faq-item").forEach(function (item) {
      var summary = q("summary", item);
      var answer = q(".faq-answer", item);
      if (!summary || !answer) {
        return;
      }
      summary.addEventListener("click", function (e) {
        e.preventDefault();
        if (item.classList.contains("is-animating")) {
          return;
        }
        item.classList.add("is-animating");
        if (!item.open) {
          item.open = true;
          gsap.fromTo(
            answer,
            { height: 0, opacity: 0 },
            {
              height: "auto", opacity: 1, duration: 0.5, ease: "power2.out",
              onComplete: function () {
                item.classList.remove("is-animating");
              }
            }
          );
        } else {
          gsap.to(answer, {
            height: 0, opacity: 0, duration: 0.4, ease: "power2.inOut",
            onComplete: function () {
              item.open = false;
              gsap.set(answer, { clearProps: "height,opacity" });
              item.classList.remove("is-animating");
            }
          });
        }
      });
    });
  })();

  ST.refresh();
})();
