// Hamburger menu toggle functionality
(function() {
  'use strict';

  document.addEventListener('DOMContentLoaded', function() {
    const hamburgerToggle = document.getElementById('hamburger-toggle');
    const mobileMenuDrawer = document.getElementById('mobile-menu-drawer');
    const mobileMenuOverlay = document.getElementById('mobile-menu-overlay');

    if (!hamburgerToggle || !mobileMenuDrawer || !mobileMenuOverlay) {
      return;
    }

    const mainContent = document.getElementById('main-content');

    function openMenu() {
      hamburgerToggle.classList.add('active');
      mobileMenuDrawer.classList.add('active');
      mobileMenuOverlay.classList.add('active');
      hamburgerToggle.setAttribute('aria-expanded', 'true');
      mobileMenuDrawer.setAttribute('aria-hidden', 'false');
      mobileMenuOverlay.setAttribute('aria-hidden', 'false');
      if (mainContent) { mainContent.setAttribute('aria-hidden', 'true'); }
      document.body.style.overflow = 'hidden';
      // Move focus into the drawer for keyboard users
      const firstFocusable = mobileMenuDrawer.querySelector('a, button, [tabindex]:not([tabindex="-1"])');
      if (firstFocusable) { firstFocusable.focus(); }
    }

    function closeMenu() {
      hamburgerToggle.classList.remove('active');
      mobileMenuDrawer.classList.remove('active');
      mobileMenuOverlay.classList.remove('active');
      hamburgerToggle.setAttribute('aria-expanded', 'false');
      mobileMenuDrawer.setAttribute('aria-hidden', 'true');
      mobileMenuOverlay.setAttribute('aria-hidden', 'true');
      if (mainContent) { mainContent.removeAttribute('aria-hidden'); }
      document.body.style.overflow = '';
      // Return focus to the toggle
      hamburgerToggle.focus();
    }

    function toggleMenu() {
      if (mobileMenuDrawer.classList.contains('active')) {
        closeMenu();
      } else {
        openMenu();
      }
    }

    // Toggle menu on hamburger click
    hamburgerToggle.addEventListener('click', function(e) {
      e.stopPropagation();
      toggleMenu();
    });

    // Close menu when clicking overlay
    mobileMenuOverlay.addEventListener('click', closeMenu);

    // Close menu when clicking a menu item
    const menuItems = mobileMenuDrawer.querySelectorAll('.mobile-menu-items a');
    menuItems.forEach(function(item) {
      item.addEventListener('click', closeMenu);
    });

    // Close menu on escape key + trap Tab focus inside the drawer while open
    document.addEventListener('keydown', function(e) {
      if (!mobileMenuDrawer.classList.contains('active')) return;

      if (e.key === 'Escape') {
        closeMenu();
        return;
      }

      if (e.key === 'Tab') {
        const focusables = mobileMenuDrawer.querySelectorAll(
          'a[href], button:not([disabled]), input:not([disabled]), [tabindex]:not([tabindex="-1"])'
        );
        if (!focusables.length) return;
        const first = focusables[0];
        const last = focusables[focusables.length - 1];
        if (e.shiftKey && document.activeElement === first) {
          e.preventDefault();
          last.focus();
        } else if (!e.shiftKey && document.activeElement === last) {
          e.preventDefault();
          first.focus();
        }
      }
    });

    // Close menu when window is resized above mobile breakpoint
    let resizeTimer;
    window.addEventListener('resize', function() {
      clearTimeout(resizeTimer);
      resizeTimer = setTimeout(function() {
        if (window.innerWidth > 768 && mobileMenuDrawer.classList.contains('active')) {
          closeMenu();
        }
      }, 250);
    });
  });
})();
