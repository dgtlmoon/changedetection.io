// Left-rail expand/collapse state.
// Adds `actionsidebar-expanded` to <body> whenever the rail is showing its
// labels. In 'pinned-expanded' mode (body.actionside-bar-on) the class is already
// present from page load; in 'expandable' mode (body.actionsidebar-minimal) the rail
// only expands on hover/focus, so we toggle the class to match. 'minimal' mode is
// also the collapsed rail but carries `actionsidebar-no-expand` and never rolls out.
(function() {
  'use strict';

  document.addEventListener('DOMContentLoaded', function() {
    if (!document.body.classList.contains('actionsidebar-minimal') ||
        document.body.classList.contains('actionsidebar-no-expand')) {
      return;
    }

    const inner = document.querySelector('.action-sidebar-inner');
    if (!inner) {
      return;
    }

    const expand = () => document.body.classList.add('actionsidebar-expanded');
    const collapse = () => document.body.classList.remove('actionsidebar-expanded');

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
