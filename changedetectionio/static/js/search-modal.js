// Search modal functionality
(function() {
  'use strict';

  document.addEventListener('DOMContentLoaded', function() {
    const searchModal = document.getElementById('search-modal');
    const openSearchButton = document.getElementById('open-search-modal');
    const closeSearchButton = document.getElementById('close-search-modal');
    const searchForm = document.getElementById('search-form');
    const searchInput = document.getElementById('search-modal-input');

    if (!searchModal || !openSearchButton) {
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

    // Open search modal on button click
    openSearchButton.addEventListener('click', openSearchModal);

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

    // Handle Alt+S keyboard shortcut
    document.addEventListener('keydown', function(e) {
      if (e.altKey && e.key.toLowerCase() === 's') {
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
        window.location.href = '/?' + params.toString();
      });
    }
  });
})();
