/**
 * Language selector modal functionality
 * Allows users to select their preferred language
 */

$(document).ready(function() {
  const $languageButton = $('.language-selector');
  const $languageModal = $('#language-modal');
  const $closeButton = $('#close-language-modal');

  if (!$languageButton.length || !$languageModal.length) {
    return;
  }

  // Open modal when language button is clicked
  $languageButton.on('click', function(e) {
    e.preventDefault();

    // Update all language links to include current hash in the redirect parameter
    const currentPath = window.location.pathname;
    const currentHash = window.location.hash;

    if (currentHash) {
      const $languageOptions = $languageModal.find('.language-option');
      $languageOptions.each(function() {
        const $option = $(this);
        const url = new URL($option.attr('href'), window.location.origin);
        // Update the redirect parameter to include the hash
        const redirectPath = currentPath + currentHash;
        url.searchParams.set('redirect', redirectPath);
        $option.attr('href', url.pathname + url.search + url.hash);
      });
    }

    $languageModal[0].showModal();
  });

  // Close modal when cancel button is clicked
  if ($closeButton.length) {
    $closeButton.on('click', function() {
      $languageModal[0].close();
    });
  }

  // Close modal when clicking outside (on backdrop)
  $languageModal.on('click', function(e) {
    const rect = this.getBoundingClientRect();
    if (
      e.clientY < rect.top ||
      e.clientY > rect.bottom ||
      e.clientX < rect.left ||
      e.clientX > rect.right
    ) {
      $languageModal[0].close();
    }
  });

  // Close modal on Escape key
  $languageModal.on('cancel', function(e) {
    e.preventDefault();
    $languageModal[0].close();
  });

  // Highlight current language
  const currentLocale = $('html').attr('lang') || 'en';
  const $languageOptions = $languageModal.find('.language-option');
  $languageOptions.each(function() {
    const $option = $(this);
    if ($option.attr('data-locale') === currentLocale) {
      $option.addClass('active');
    }
  });
});
