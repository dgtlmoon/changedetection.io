/**
 * Modern modal dialog system using HTML5 <dialog> element
 * Provides accessible, animated confirmation dialogs
 */

const ModalDialog = {
  /**
   * Show a confirmation dialog
   * @param {Object} options - Configuration options
   * @param {string} options.title - Dialog title
   * @param {string} options.message - Dialog message (can include HTML)
   * @param {string} options.type - Dialog type: 'danger', 'warning', or 'info' (default: 'info')
   * @param {string} options.confirmText - Confirm button text (default: 'Confirm')
   * @param {string} options.cancelText - Cancel button text (default: 'Cancel')
   * @param {Function} options.onConfirm - Callback when confirmed
   * @param {Function} options.onCancel - Callback when cancelled (optional)
   * @returns {Promise} Resolves with true if confirmed, false if cancelled
   */
  confirm: function(options) {
    return new Promise((resolve) => {
      const defaults = {
        title: 'Confirm Action',
        message: 'Are you sure?',
        type: 'info',
        confirmText: 'Confirm',
        cancelText: 'Cancel',
        onConfirm: null,
        onCancel: null
      };

      const config = { ...defaults, ...options };

      // Icon mapping
      const icons = {
        danger: '⚠️',
        warning: '⚠️',
        info: 'ℹ️'
      };

      // Create dialog element
      const dialog = document.createElement('dialog');
      dialog.className = 'modal-dialog';
      dialog.setAttribute('aria-labelledby', 'modal-title');
      dialog.setAttribute('aria-describedby', 'modal-body');

      // Build dialog content
      dialog.innerHTML = `
        <div class="modal-header">
          <span class="modal-icon ${config.type}">${icons[config.type] || icons.info}</span>
          <h2 class="modal-title" id="modal-title">${config.title}</h2>
        </div>
        <div class="modal-body" id="modal-body">
          ${config.message}
        </div>
        <div class="modal-footer">
          <button type="button" class="modal-btn-cancel pure-button" data-action="cancel">
            ${config.cancelText}
          </button>
          <button type="button" class="modal-btn-${config.type} pure-button" data-action="confirm">
            ${config.confirmText}
          </button>
        </div>
      `;

      // Append to body
      document.body.appendChild(dialog);

      // Handle button clicks
      const handleClose = (confirmed) => {
        dialog.close();
        setTimeout(() => {
          dialog.remove();
        }, 200);

        if (confirmed && config.onConfirm) {
          config.onConfirm();
        } else if (!confirmed && config.onCancel) {
          config.onCancel();
        }

        resolve(confirmed);
      };

      // Attach event listeners
      dialog.querySelector('[data-action="confirm"]').addEventListener('click', () => {
        handleClose(true);
      });

      dialog.querySelector('[data-action="cancel"]').addEventListener('click', () => {
        handleClose(false);
      });

      // Handle Escape key
      dialog.addEventListener('cancel', (e) => {
        e.preventDefault();
        handleClose(false);
      });

      // Handle backdrop click
      dialog.addEventListener('click', (e) => {
        const rect = dialog.getBoundingClientRect();
        if (
          e.clientY < rect.top ||
          e.clientY > rect.bottom ||
          e.clientX < rect.left ||
          e.clientX > rect.right
        ) {
          handleClose(false);
        }
      });

      // Show dialog
      dialog.showModal();

      // Focus confirm button for accessibility
      setTimeout(() => {
        dialog.querySelector('[data-action="confirm"]').focus();
      }, 100);
    });
  },

  /**
   * Helper method for delete confirmations
   * @param {string} itemName - Name of the item being deleted
   * @param {Function} onConfirm - Callback when confirmed
   */
  confirmDelete: function(itemName, onConfirm) {
    return this.confirm({
      title: 'Delete ' + itemName + '?',
      message: `<p>Are you sure you want to delete <strong>${itemName}</strong>?</p><p>This action cannot be undone.</p>`,
      type: 'danger',
      confirmText: 'Delete',
      cancelText: 'Cancel',
      onConfirm: onConfirm
    });
  },

  /**
   * Helper method for unlink confirmations
   * @param {string} itemName - Name of the item being unlinked
   * @param {Function} onConfirm - Callback when confirmed
   */
  confirmUnlink: function(itemName, onConfirm) {
    return this.confirm({
      title: 'Unlink ' + itemName + '?',
      message: `<p>Are you sure you want to unlink all watches from <strong>${itemName}</strong>?</p><p>The tag will be kept but watches will be removed from it.</p>`,
      type: 'warning',
      confirmText: 'Unlink',
      cancelText: 'Cancel',
      onConfirm: onConfirm
    });
  }
};

// Make available globally
window.ModalDialog = ModalDialog;

/**
 * Auto-attach modal confirmations to links with data-requires-confirm attribute
 * Usage in HTML:
 * <a href="/delete"
 *    data-requires-confirm
 *    data-confirm-type="danger"
 *    data-confirm-title="Delete Item?"
 *    data-confirm-message="Are you sure?"
 *    data-confirm-button="Delete">
 */
$(document).ready(function() {
  $(document).on('click', 'a[data-requires-confirm], button[data-requires-confirm]', function(e) {
    e.preventDefault();
    const $element = $(this);
    const url = $element.attr('href');

    const config = {
      type: $element.data('confirm-type') || 'danger',
      title: $element.data('confirm-title') || 'Confirm Action',
      message: $element.data('confirm-message') || '<p>Are you sure you want to proceed?</p>',
      confirmText: $element.data('confirm-button') || 'Confirm',
      cancelText: $element.data('cancel-button') || 'Cancel',
      onConfirm: function() {
        // If it's a link, navigate to the URL
        if ($element.is('a')) {
          window.location.href = url;
        }
        // If it's a button in a form, submit the form
        else if ($element.is('button')) {
          // Use requestSubmit() to include the button's name/value in the form data
          $element.closest('form')[0].requestSubmit($element[0]);
        }
      }
    };

    ModalDialog.confirm(config);
  });
});
