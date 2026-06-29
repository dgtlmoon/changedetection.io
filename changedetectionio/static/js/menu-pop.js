// "More" overflow menu (the kebab button in the top menu). Toggles its sibling
// .menu-pop open/closed; closes on click-outside, Escape, or selecting an item.
(function () {
  'use strict';

  document.addEventListener('DOMContentLoaded', function () {
    const toggles = Array.prototype.slice.call(document.querySelectorAll('.js-menu-more-toggle'));
    if (!toggles.length) return;

    function closeAll() {
      document.querySelectorAll('.menu-pop.open').forEach(function (pop) {
        pop.classList.remove('open');
      });
      toggles.forEach(function (t) { t.setAttribute('aria-expanded', 'false'); });
    }

    toggles.forEach(function (toggle) {
      const pop = toggle.parentElement.querySelector('.menu-pop');
      if (!pop) return;

      toggle.addEventListener('click', function (e) {
        e.stopPropagation();
        const willOpen = !pop.classList.contains('open');
        closeAll();
        if (willOpen) {
          pop.classList.add('open');
          toggle.setAttribute('aria-expanded', 'true');
        }
      });

      // Selecting an item dismisses the menu (the item's own action still runs).
      pop.querySelectorAll('.mi').forEach(function (item) {
        item.addEventListener('click', closeAll);
      });
    });

    // Click outside / Escape closes any open popup.
    document.addEventListener('click', function (e) {
      if (!e.target.closest('.menu-pop-wrap')) closeAll();
    });
    document.addEventListener('keydown', function (e) {
      if (e.key === 'Escape') closeAll();
    });
  });
})();
