/* Applyocalypse landing page interactions. Vanilla, no dependencies. */
(function () {
  'use strict';

  var reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  /* ---- Sticky nav condense ---------------------------------------------- */
  var nav = document.getElementById('nav');
  var onScroll = function () {
    if (window.scrollY > 24) {
      nav.classList.add('is-stuck');
    } else {
      nav.classList.remove('is-stuck');
    }
  };
  window.addEventListener('scroll', onScroll, { passive: true });
  onScroll();

  /* ---- Mobile menu ------------------------------------------------------- */
  var burger = document.getElementById('burger');
  var navLinks = document.getElementById('nav-links');
  var closeMenu = function () {
    nav.classList.remove('is-open');
    burger.setAttribute('aria-expanded', 'false');
  };
  burger.addEventListener('click', function () {
    var open = nav.classList.toggle('is-open');
    burger.setAttribute('aria-expanded', open ? 'true' : 'false');
  });
  navLinks.addEventListener('click', function (e) {
    if (e.target.closest('a')) {
      closeMenu();
    }
  });
  window.addEventListener('resize', function () {
    if (window.innerWidth > 900) {
      closeMenu();
    }
  });

  /* ---- Reveal on scroll -------------------------------------------------- */
  var revealEls = document.querySelectorAll('[data-reveal]');
  if (reduceMotion || !('IntersectionObserver' in window)) {
    revealEls.forEach(function (el) {
      el.classList.add('is-in');
    });
  } else {
    var revealObserver = new IntersectionObserver(
      function (entries, obs) {
        entries.forEach(function (entry) {
          if (!entry.isIntersecting) {
            return;
          }
          var el = entry.target;
          if (el.getAttribute('data-reveal') === 'stagger') {
            var kids = el.children;
            for (var i = 0; i < kids.length; i++) {
              kids[i].style.transitionDelay = i * 90 + 'ms';
            }
          }
          el.classList.add('is-in');
          obs.unobserve(el);
        });
      },
      { threshold: 0.14, rootMargin: '0px 0px -8% 0px' }
    );
    revealEls.forEach(function (el) {
      revealObserver.observe(el);
    });
  }

  /* ---- Five-step scrolly ------------------------------------------------- */
  var steps = Array.prototype.slice.call(document.querySelectorAll('.how-step'));
  var visuals = Array.prototype.slice.call(document.querySelectorAll('.how-visual'));

  if (steps.length && visuals.length) {
    var setActive = function (index) {
      steps.forEach(function (s, i) {
        s.classList.toggle('active', i === index);
      });
      visuals.forEach(function (v, i) {
        v.classList.toggle('is-active', i === index);
      });
    };

    if ('IntersectionObserver' in window) {
      var stepObserver = new IntersectionObserver(
        function (entries) {
          entries.forEach(function (entry) {
            if (entry.isIntersecting) {
              var idx = parseInt(entry.target.getAttribute('data-step'), 10);
              if (!isNaN(idx)) {
                setActive(idx);
              }
            }
          });
        },
        /* zero-height band across the vertical middle of the viewport */
        { rootMargin: '-50% 0px -50% 0px', threshold: 0 }
      );
      steps.forEach(function (s) {
        stepObserver.observe(s);
      });
    }
  }

  /* ---- Showcase pointer tilt -------------------------------------------- */
  var tilt = document.getElementById('tilt');
  if (tilt && !reduceMotion && window.matchMedia('(pointer: fine)').matches) {
    var frame = tilt.querySelector('.app-window');
    var raf = null;
    var apply = function (rx, ry) {
      frame.style.transform = 'rotateX(' + rx + 'deg) rotateY(' + ry + 'deg)';
    };
    tilt.addEventListener('pointermove', function (e) {
      var rect = tilt.getBoundingClientRect();
      var px = (e.clientX - rect.left) / rect.width - 0.5;
      var py = (e.clientY - rect.top) / rect.height - 0.5;
      if (raf) {
        cancelAnimationFrame(raf);
      }
      raf = requestAnimationFrame(function () {
        apply(6 - py * 8, px * 9);
      });
    });
    tilt.addEventListener('pointerleave', function () {
      if (raf) {
        cancelAnimationFrame(raf);
      }
      apply(6, 0);
    });
  }
})();
