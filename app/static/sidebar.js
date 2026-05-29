/* SPDX-FileCopyrightText: Copyright Siemens 2026 */
/* SPDX-License-Identifier: Apache-2.0 */
/**
 * Sidebar navigation controller.
 *
 * Handles:
 *  - Expand / collapse with spring-physics CSS transitions
 *  - Staggered label reveal via --nav-index custom property
 *  - Fluid hamburger → X icon morph (CSS-driven)
 *  - Mobile: off-canvas overlay with backdrop-blur, focus trapping, body scroll-lock
 *  - Keyboard: Escape to close, Tab cycling trapped in mobile overlay
 *  - WAI-ARIA: aria-expanded, aria-controls on toggle; semantic <nav>
 *  - Respects prefers-reduced-motion (animation timing handled in CSS)
 */
(function () {
  'use strict';

  var sidebar = document.getElementById('sidebar');
  var hamburger = document.getElementById('hamburger-btn');
  var overlay = document.getElementById('sidebar-overlay');
  if (!sidebar || !hamburger) return;

  var FOCUSABLE =
    'a[href]:not([tabindex="-1"]), button:not([disabled]):not([tabindex="-1"])';
  var isExpanded = false;
  var reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)');

  function isMobile() {
    return window.matchMedia('(max-width: 768px)').matches;
  }

  // Assign --nav-index on every sidebar link so CSS can compute
  // per-item stagger delays: transition-delay: calc(var(--nav-index) * 60ms + 100ms)
  var allLinks = sidebar.querySelectorAll('.sidebar-link');
  for (var i = 0; i < allLinks.length; i++) {
    allLinks[i].style.setProperty('--nav-index', i);
  }

  /* ── Open ──────────────────────────────────────────────── */
  function open() {
    isExpanded = true;
    sidebar.classList.add('expanded');
    hamburger.setAttribute('aria-expanded', 'true');
    hamburger.setAttribute('aria-label', 'Close navigation menu');

    if (isMobile()) {
      if (overlay) overlay.classList.add('active');
      document.body.classList.add('sidebar-open');

      // After the slide-in + stagger animation completes, move focus
      // into the nav for immediate keyboard access.
      var delay = reducedMotion.matches ? 50 : 380;
      setTimeout(function () {
        var first = sidebar.querySelector('.sidebar-nav .sidebar-link');
        if (first) first.focus();
      }, delay);
    }
  }

  /* ── Close ─────────────────────────────────────────────── */
  function close() {
    isExpanded = false;
    sidebar.classList.remove('expanded');
    hamburger.setAttribute('aria-expanded', 'false');
    hamburger.setAttribute('aria-label', 'Open navigation menu');

    if (overlay) overlay.classList.remove('active');
    document.body.classList.remove('sidebar-open');
    hamburger.focus();
  }

  /* ── Toggle ────────────────────────────────────────────── */
  hamburger.addEventListener('click', function () {
    isExpanded ? close() : open();
  });

  /* ── Backdrop click closes (mobile) ────────────────────── */
  if (overlay) {
    overlay.addEventListener('click', function () {
      if (isExpanded) close();
    });
  }

  /* ── Escape key closes ─────────────────────────────────── */
  document.addEventListener('keydown', function (e) {
    if (e.key === 'Escape' && isExpanded) {
      e.preventDefault();
      close();
    }
  });

  /* ── Focus trap (mobile overlay) ───────────────────────── */
  // When the overlay is open on mobile, Tab must cycle only through
  // the sidebar's focusable elements to prevent invisible-behind-overlay
  // elements from receiving focus.
  sidebar.addEventListener('keydown', function (e) {
    if (e.key !== 'Tab' || !isExpanded || !isMobile()) return;

    var focusables = [];
    var all = sidebar.querySelectorAll(FOCUSABLE);
    for (var j = 0; j < all.length; j++) {
      if (all[j].offsetParent !== null) focusables.push(all[j]);
    }
    if (focusables.length === 0) return;

    var first = focusables[0];
    var last = focusables[focusables.length - 1];

    if (e.shiftKey && document.activeElement === first) {
      e.preventDefault();
      last.focus();
    } else if (!e.shiftKey && document.activeElement === last) {
      e.preventDefault();
      first.focus();
    }
  });

  /* ── Sync overlay when viewport crosses the breakpoint ─── */
  var wasMobile = isMobile();
  window.addEventListener('resize', function () {
    var nowMobile = isMobile();
    if (wasMobile !== nowMobile && isExpanded) {
      if (nowMobile) {
        document.body.classList.add('sidebar-open');
        if (overlay) overlay.classList.add('active');
      } else {
        document.body.classList.remove('sidebar-open');
        if (overlay) overlay.classList.remove('active');
      }
    }
    wasMobile = nowMobile;
  });
})();
