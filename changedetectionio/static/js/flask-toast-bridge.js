/**
 * Flask Toast Bridge
 * Automatically converts Flask flash messages to toast notifications
 *
 * Maps Flask message categories to toast types:
 * - 'message' or 'info' -> info toast
 * - 'success' -> success toast
 * - 'error' or 'danger' -> error toast
 * - 'warning' -> warning toast
 */

(function() {
  'use strict';

  document.addEventListener('DOMContentLoaded', function() {
    // Find the Flask messages container
    const messagesContainer = document.querySelector('ul.messages');

    if (!messagesContainer) {
      return;
    }

    // Get all flash messages
    const messages = messagesContainer.querySelectorAll('li');

    if (messages.length === 0) {
      return;
    }

    let toastIndex = 0;

    // Convert each message to a toast (except errors)
    messages.forEach(function(messageEl) {
      const text = messageEl.textContent.trim();
      const category = getMessageCategory(messageEl);

      // Skip error messages - they should stay in the page
      if (category === 'error') {
        return;
      }

      const toastType = mapCategoryToToastType(category);

      // Stagger toast appearance for multiple messages
      setTimeout(function() {
        Toast[toastType](text, {
          duration: 6000  // 6 seconds for Flask messages
        });
      }, toastIndex * 200);  // 200ms delay between each toast

      toastIndex++;

      // Hide this specific message element (not errors)
      messageEl.style.display = 'none';
    });
  });

  /**
   * Extract message category from class names
   */
  function getMessageCategory(messageEl) {
    const classes = messageEl.className.split(' ');

    // Common Flask flash message categories
    const categoryMap = {
      'success': 'success',
      'error': 'error',
      'danger': 'error',
      'warning': 'warning',
      'info': 'info',
      'message': 'info',
      'notice': 'info'
    };

    for (let className of classes) {
      if (categoryMap[className]) {
        return categoryMap[className];
      }
    }

    // Default to info if no category found
    return 'info';
  }

  /**
   * Map Flask category to Toast type
   */
  function mapCategoryToToastType(category) {
    const typeMap = {
      'success': 'success',
      'error': 'error',
      'warning': 'warning',
      'info': 'info'
    };

    return typeMap[category] || 'info';
  }

})();
