// Left-rail expand/collapse state.
// Adds `action-side-bar-expanded` to <body> whenever the rail is showing its
// labels. In pinned mode (body.actionside-bar-on) the class is already present
// from page load; in collapsed mode (body.actionsidebar-minimal) the rail only
// expands on hover/focus, so we toggle the class to match.
(function() {
  'use strict';

  document.addEventListener('DOMContentLoaded', function() {
    if (!document.body.classList.contains('actionsidebar-minimal')) {
      return;
    }

    const inner = document.querySelector('.action-sidebar-inner');
    if (!inner) {
      return;
    }

    const expand = () => document.body.classList.add('action-side-bar-expanded');
    const collapse = () => document.body.classList.remove('action-side-bar-expanded');

    inner.addEventListener('mouseenter', expand);
    inner.addEventListener('mouseleave', collapse);
    inner.addEventListener('focusin', expand);
    inner.addEventListener('focusout', function(e) {
      // Keep expanded while focus stays inside the rail.
      if (!inner.contains(e.relatedTarget)) {
        collapse();
      }
    });
  });
})();
