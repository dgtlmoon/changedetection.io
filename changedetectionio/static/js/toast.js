/**
 * Toast - Modern toast notification system
 * Inspired by Toastify, Notyf, and React Hot Toast
 *
 * Usage:
 *   Toast.success('Operation completed!');
 *   Toast.error('Something went wrong');
 *   Toast.info('Here is some information');
 *   Toast.warning('Warning message');
 *   Toast.show('Custom message', { type: 'success', duration: 3000 });
 *
 * License: MIT
 */

(function(window) {
  'use strict';

  // Toast configuration
  const defaultConfig = {
    duration: 5000,        // Auto-dismiss after 5 seconds (0 = no auto-dismiss)
    position: 'top-center', // top-right, top-center, top-left, bottom-right, bottom-center, bottom-left
    closeButton: true,     // Show close button
    progressBar: true,     // Show progress bar
    pauseOnHover: true,    // Pause auto-dismiss on hover
    maxToasts: 5,          // Maximum toasts to show at once
    offset: '20px',        // Offset from edge
    zIndex: 10000,         // Z-index for toast container
  };

  let config = { ...defaultConfig };
  let toastCount = 0;
  let container = null;

  /**
   * Initialize toast system with custom config
   */
  function init(userConfig = {}) {
    config = { ...defaultConfig, ...userConfig };
    createContainer();
  }

  /**
   * Create toast container if it doesn't exist
   */
  function createContainer() {
    if (container) return;

    container = document.createElement('div');
    container.className = `toast-container toast-${config.position}`;
    container.style.zIndex = config.zIndex;
    document.body.appendChild(container);
  }

  /**
   * Show a toast notification
   */
  function show(message, options = {}) {
    createContainer();

    const toast = createToastElement(message, options);

    // Limit number of toasts
    const existingToasts = container.querySelectorAll('.toast');
    if (existingToasts.length >= config.maxToasts) {
      removeToast(existingToasts[0]);
    }

    // Add to container
    container.appendChild(toast);

    // Trigger animation
    requestAnimationFrame(() => {
      toast.classList.add('toast-show');
    });

    // Auto-dismiss
    if (options.duration !== 0 && (options.duration || config.duration) > 0) {
      setupAutoDismiss(toast, options.duration || config.duration);
    }

    return {
      dismiss: () => removeToast(toast)
    };
  }

  /**
   * Create toast DOM element
   */
  function createToastElement(message, options) {
    const toast = document.createElement('div');
    toast.className = `toast toast-${options.type || 'default'}`;
    toast.setAttribute('role', 'alert');
    toast.setAttribute('aria-live', 'polite');

    // Icon
    const icon = createIcon(options.type || 'default');
    if (icon) {
      toast.appendChild(icon);
    }

    // Message
    const messageEl = document.createElement('div');
    messageEl.className = 'toast-message';
    messageEl.textContent = message;
    toast.appendChild(messageEl);

    // Close button
    if (options.closeButton !== false && config.closeButton) {
      const closeBtn = document.createElement('button');
      closeBtn.className = 'toast-close';
      closeBtn.innerHTML = '&times;';
      closeBtn.setAttribute('aria-label', 'Close');
      closeBtn.onclick = () => removeToast(toast);
      toast.appendChild(closeBtn);
    }

    // Progress bar
    if (options.progressBar !== false && config.progressBar && (options.duration || config.duration) > 0) {
      const progressBar = document.createElement('div');
      progressBar.className = 'toast-progress';
      toast.appendChild(progressBar);
      toast._progressBar = progressBar;
    }

    return toast;
  }

  /**
   * Create icon based on toast type
   */
  function createIcon(type) {
    const iconEl = document.createElement('div');
    iconEl.className = 'toast-icon';

    const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    svg.setAttribute('viewBox', '0 0 24 24');
    svg.setAttribute('fill', 'none');
    svg.setAttribute('stroke', 'currentColor');
    svg.setAttribute('stroke-width', '2');

    let path = '';
    switch (type) {
      case 'success':
        path = 'M20 6L9 17l-5-5';
        break;
      case 'error':
        path = 'M18 6L6 18M6 6l12 12';
        break;
      case 'warning':
        path = 'M12 9v4m0 4h.01M12 2a10 10 0 100 20 10 10 0 000-20z';
        svg.setAttribute('stroke-width', '1.5');
        break;
      case 'info':
        path = 'M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z';
        svg.setAttribute('stroke-width', '1.5');
        break;
      default:
        return null;
    }

    const pathEl = document.createElementNS('http://www.w3.org/2000/svg', 'path');
    pathEl.setAttribute('d', path);
    pathEl.setAttribute('stroke-linecap', 'round');
    pathEl.setAttribute('stroke-linejoin', 'round');
    svg.appendChild(pathEl);
    iconEl.appendChild(svg);

    return iconEl;
  }

  /**
   * Setup auto-dismiss with progress bar
   */
  function setupAutoDismiss(toast, duration) {
    let startTime = Date.now();
    let remainingTime = duration;
    let isPaused = false;
    let animationFrame;

    function updateProgress() {
      if (isPaused) return;

      const elapsed = Date.now() - startTime;
      const progress = Math.min(elapsed / duration, 1);

      if (toast._progressBar) {
        toast._progressBar.style.transform = `scaleX(${1 - progress})`;
      }

      if (progress >= 1) {
        removeToast(toast);
      } else {
        animationFrame = requestAnimationFrame(updateProgress);
      }
    }

    // Pause on hover
    if (config.pauseOnHover) {
      toast.addEventListener('mouseenter', () => {
        isPaused = true;
        remainingTime = duration - (Date.now() - startTime);
        cancelAnimationFrame(animationFrame);
      });

      toast.addEventListener('mouseleave', () => {
        isPaused = false;
        startTime = Date.now();
        duration = remainingTime;
        animationFrame = requestAnimationFrame(updateProgress);
      });
    }

    animationFrame = requestAnimationFrame(updateProgress);
  }

  /**
   * Remove toast with animation
   */
  function removeToast(toast) {
    if (!toast || !toast.parentElement) return;

    toast.classList.add('toast-hide');

    // Remove after animation
    setTimeout(() => {
      if (toast.parentElement) {
        toast.parentElement.removeChild(toast);
      }
    }, 300);
  }

  // Convenience methods
  function success(message, options = {}) {
    return show(message, { ...options, type: 'success' });
  }

  function error(message, options = {}) {
    return show(message, { ...options, type: 'error' });
  }

  function warning(message, options = {}) {
    return show(message, { ...options, type: 'warning' });
  }

  function info(message, options = {}) {
    return show(message, { ...options, type: 'info' });
  }

  /**
   * Clear all toasts
   */
  function clear() {
    if (!container) return;
    const toasts = container.querySelectorAll('.toast');
    toasts.forEach(removeToast);
  }

  // Public API
  window.Toast = {
    init,
    show,
    success,
    error,
    warning,
    info,
    clear,
    version: '1.0.0'
  };

  // Auto-initialize
  document.addEventListener('DOMContentLoaded', () => {
    init();
  });

})(window);
