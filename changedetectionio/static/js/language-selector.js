/**
 * Language selector modal functionality
 * Allows users to select their preferred language
 */

document.addEventListener('DOMContentLoaded', function() {
  const languageButton = document.getElementById('language-selector');
  const languageModal = document.getElementById('language-modal');
  const closeButton = document.getElementById('close-language-modal');

  if (!languageButton || !languageModal) {
    return;
  }

  // Open modal when language button is clicked
  languageButton.addEventListener('click', function(e) {
    e.preventDefault();
    languageModal.showModal();
  });

  // Close modal when cancel button is clicked
  if (closeButton) {
    closeButton.addEventListener('click', function() {
      languageModal.close();
    });
  }

  // Close modal when clicking outside (on backdrop)
  languageModal.addEventListener('click', function(e) {
    const rect = languageModal.getBoundingClientRect();
    if (
      e.clientY < rect.top ||
      e.clientY > rect.bottom ||
      e.clientX < rect.left ||
      e.clientX > rect.right
    ) {
      languageModal.close();
    }
  });

  // Close modal on Escape key
  languageModal.addEventListener('cancel', function(e) {
    e.preventDefault();
    languageModal.close();
  });

  // Highlight current language
  const currentLocale = document.documentElement.lang || 'en';
  const languageOptions = languageModal.querySelectorAll('.language-option');
  languageOptions.forEach(function(option) {
    if (option.dataset.locale === currentLocale) {
      option.classList.add('active');
    }
  });
});
