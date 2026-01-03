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

    function openMenu() {
      hamburgerToggle.classList.add('active');
      mobileMenuDrawer.classList.add('active');
      mobileMenuOverlay.classList.add('active');
      document.body.style.overflow = 'hidden';
    }

    function closeMenu() {
      hamburgerToggle.classList.remove('active');
      mobileMenuDrawer.classList.remove('active');
      mobileMenuOverlay.classList.remove('active');
      document.body.style.overflow = '';
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

    // Close menu on escape key
    document.addEventListener('keydown', function(e) {
      if (e.key === 'Escape' && mobileMenuDrawer.classList.contains('active')) {
        closeMenu();
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
