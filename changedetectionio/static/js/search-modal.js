// Search modal functionality
(function() {
  'use strict';

  document.addEventListener('DOMContentLoaded', function() {
    const searchModal = document.getElementById('search-modal');
    // The Search button is rendered in the left rail and the mobile drawer.
    const openSearchButtons = document.querySelectorAll('.js-open-search-modal');
    const closeSearchButton = document.getElementById('close-search-modal');
    const searchForm = document.getElementById('search-form');
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

    // Handle Enter key in search input
    if (searchInput) {
      searchInput.addEventListener('keydown', function(e) {
        if (e.key === 'Enter') {
          e.preventDefault();
          if (searchForm) {
            // Trigger form submission programmatically
            searchForm.dispatchEvent(new Event('submit'));
          }
        }
      });
    }

    // Handle form submission
    if (searchForm) {
      searchForm.addEventListener('submit', function(e) {
        e.preventDefault();

        // Get form data
        const formData = new FormData(searchForm);
        const searchQuery = formData.get('q');
        const tags = formData.get('tags');

        // Build URL
        const params = new URLSearchParams();
        if (searchQuery) {
          params.append('q', searchQuery);
        }
        if (tags) {
          params.append('tags', tags);
        }

        // Navigate to search results (always redirect to watchlist home)
        // Use base_path if available (for sub-path deployments like /enlighten-richerx)
        const basePath = typeof base_path !== 'undefined' ? base_path : '';
        window.location.href = basePath + '/?' + params.toString();
      });
    }
  });
})();
