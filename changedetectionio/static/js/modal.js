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
      dialog.setAttribute('aria-modal', 'true');
      dialog.setAttribute('role', 'alertdialog');

      // Build dialog content with DOM APIs (not innerHTML) so user-supplied
      // strings in config.title / config.message / button text cannot inject HTML.
      // Callers that need rich markup in the body must pass `messageHtml` with
      // trusted, pre-sanitized HTML instead of plain `message`.
      const header = document.createElement('div');
      header.className = 'modal-header';
      const iconEl = document.createElement('span');
      iconEl.className = 'modal-icon ' + config.type;
      iconEl.textContent = icons[config.type] || icons.info;
      const titleEl = document.createElement('h2');
      titleEl.className = 'modal-title';
      titleEl.id = 'modal-title';
      titleEl.textContent = config.title;
      header.appendChild(iconEl);
      header.appendChild(titleEl);

      const body = document.createElement('div');
      body.className = 'modal-body';
      body.id = 'modal-body';
      if (typeof config.messageHtml === 'string') {
        // Trusted HTML path — caller is responsible for sanitization.
        body.innerHTML = config.messageHtml;
      } else {
        body.textContent = config.message;
      }

      const footer = document.createElement('div');
      footer.className = 'modal-footer';
      const cancelBtn = document.createElement('button');
      cancelBtn.type = 'button';
      cancelBtn.className = 'modal-btn-cancel pure-button';
      cancelBtn.dataset.action = 'cancel';
      cancelBtn.textContent = config.cancelText;
      const confirmBtn = document.createElement('button');
      confirmBtn.type = 'button';
      confirmBtn.className = 'modal-btn-' + config.type + ' pure-button';
      confirmBtn.dataset.action = 'confirm';
      confirmBtn.textContent = config.confirmText;
      footer.appendChild(cancelBtn);
      footer.appendChild(confirmBtn);

      dialog.appendChild(header);
      dialog.appendChild(body);
      dialog.appendChild(footer);

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
   * Escape a string so it can safely be embedded in HTML.
   * Used by helper methods that build small HTML snippets around user-supplied names.
   */
  _escapeHtml: function(str) {
    return String(str).replace(/[&<>"']/g, function(c) {
      return ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'})[c];
    });
  },

  /**
   * Helper method for delete confirmations
   * @param {string} itemName - Name of the item being deleted
   * @param {Function} onConfirm - Callback when confirmed
   */
  confirmDelete: function(itemName, onConfirm) {
    const safeName = this._escapeHtml(itemName);
    return this.confirm({
      title: 'Delete ' + itemName + '?',
      messageHtml: `<p>Are you sure you want to delete <strong>${safeName}</strong>?</p><p>This action cannot be undone.</p>`,
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
    const safeName = this._escapeHtml(itemName);
    return this.confirm({
      title: 'Unlink ' + itemName + '?',
      messageHtml: `<p>Are you sure you want to unlink all watches from <strong>${safeName}</strong>?</p><p>The tag will be kept but watches will be removed from it.</p>`,
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

    // data-confirm-message is rendered as plain text (via textContent) to
    // prevent HTML injection from server-generated attribute values.
    const config = {
      type: $element.data('confirm-type') || 'danger',
      title: $element.data('confirm-title') || 'Confirm Action',
      message: $element.data('confirm-message') || 'Are you sure you want to proceed?',
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
