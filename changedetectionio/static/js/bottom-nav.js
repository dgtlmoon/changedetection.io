// Mobile bottom navigation bar — wire up Search and More buttons to the
// existing search modal / hamburger drawer, so we don't duplicate their
// open/close logic here.
(function () {
  'use strict';

  document.addEventListener('DOMContentLoaded', function () {
    var nav = document.querySelector('.mobile-bottom-nav');
    if (!nav) return;

    // Search → delegate to the existing #open-search-modal button, which
    // search-modal.js already has a listener on. This avoids re-implementing
    // dialog.showModal() and the focus/close dance.
    var searchBtn = nav.querySelector('.bottom-nav-search');
    if (searchBtn) {
      searchBtn.addEventListener('click', function () {
        var existing = document.getElementById('open-search-modal');
        if (existing) {
          existing.click();
          return;
        }
        // Fallback: if the top-nav button isn't present (e.g. DOM tweak),
        // open the dialog directly.
        var modal = document.getElementById('search-modal');
        if (modal && typeof modal.showModal === 'function') {
          modal.showModal();
        }
      });
    }

    // More → trigger the existing hamburger toggle. hamburger-menu.js handles
    // the open/close, overlay, escape-key, and body-scroll lock already.
    var moreBtn = nav.querySelector('.bottom-nav-more');
    if (moreBtn) {
      moreBtn.addEventListener('click', function () {
        var hamb = document.getElementById('hamburger-toggle');
        if (hamb) hamb.click();
      });
    }
  });
})();
