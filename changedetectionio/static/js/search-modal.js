// Search modal functionality
(function() {
  'use strict';

  document.addEventListener('DOMContentLoaded', function() {
    const searchModal = document.getElementById('search-modal');
    // The Search button is rendered in the left rail and the mobile drawer.
    const openSearchButtons = document.querySelectorAll('.js-open-search-modal');
    const closeSearchButton = document.getElementById('close-search-modal');
    const searchInput = document.getElementById('search-modal-input');

    if (!searchModal || openSearchButtons.length === 0) {
      return;
    }

    // Open modal
    function openSearchModal() {
      searchModal.showModal();
      // Focus the input after a small delay to ensure modal is rendered
      setTimeout(function() {
        if (searchInput) {
          searchInput.focus();
        }
      }, 100);
    }

    // Close modal
    function closeSearchModal() {
      searchModal.close();
      if (searchInput) {
        searchInput.value = '';
      }
    }

    // Open search modal on button click (desktop + mobile drawer)
    openSearchButtons.forEach(function(btn) {
      btn.addEventListener('click', function(e) {
        // Close mobile drawer if open, so the modal isn't behind it
        const drawer = document.getElementById('mobile-menu-drawer');
        const overlay = document.getElementById('mobile-menu-overlay');
        const toggle = document.getElementById('hamburger-toggle');
        if (drawer && drawer.classList.contains('active')) {
          drawer.classList.remove('active');
          if (overlay) overlay.classList.remove('active');
          if (toggle) toggle.classList.remove('active');
        }
        openSearchModal();
      });
    });

    // Close modal on cancel button
    if (closeSearchButton) {
      closeSearchButton.addEventListener('click', closeSearchModal);
    }

    // Close modal on escape key (native behavior for dialog)
    searchModal.addEventListener('cancel', function(e) {
      if (searchInput) {
        searchInput.value = '';
      }
    });

    // Close modal when clicking the backdrop
    searchModal.addEventListener('click', function(e) {
      // Only real pointer clicks can land on the backdrop. Keyboard-synthesised clicks
      // report detail 0 and coordinates of 0,0, which the geometry test below reads as
      // "outside the dialog" - and implicit form submission (Enter in the input) fires
      // exactly such a click at the Search button. That closed the modal and blanked
      // the input mid-dispatch, so the submit that followed hit an empty `required`
      // field and was rejected: Enter appeared to just dismiss the form.
      if (e.detail === 0) {
        return;
      }
      const rect = searchModal.getBoundingClientRect();
      const isInDialog = (
        rect.top <= e.clientY &&
        e.clientY <= rect.top + rect.height &&
        rect.left <= e.clientX &&
        e.clientX <= rect.left + rect.width
      );
      if (!isInDialog) {
        closeSearchModal();
      }
    });

    // Keyboard shortcuts: Alt+S, and "/" (when not already typing in a field).
    document.addEventListener('keydown', function(e) {
      if (e.altKey && e.key.toLowerCase() === 's') {
        e.preventDefault();
        openSearchModal();
        return;
      }
      if (e.key === '/' && !e.altKey && !e.ctrlKey && !e.metaKey) {
        const t = e.target;
        const tag = t && t.tagName ? t.tagName.toLowerCase() : '';
        if (tag === 'input' || tag === 'textarea' || tag === 'select' || (t && t.isContentEditable)) {
          return; // let "/" type normally in form fields
        }
        e.preventDefault();
        openSearchModal();
      }
    });

    // Submission is left to the browser: the form carries a server-rendered action
    // (correct under a reverse-proxy sub-path) and Enter in the input triggers implicit
    // submission via the footer's submit button, which also runs `required` validation.
  });
})();
