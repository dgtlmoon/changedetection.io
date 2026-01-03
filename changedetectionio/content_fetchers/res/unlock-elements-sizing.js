/**
 * Unlock Element Dimensions After Screenshot Capture
 *
 * This script removes the inline !important styles that were applied by lock-elements-sizing.js
 * and restores elements to their original state using the WeakMap created during locking.
 *
 * USAGE:
 * Execute this script AFTER completing screenshot capture and restoring the viewport.
 * This allows the page to return to its normal responsive behavior.
 *
 * WHAT THIS SCRIPT DOES:
 * 1. Iterates through every element that was locked
 * 2. Reads original style values from the global WeakMap
 * 3. Restores original inline styles (or removes them if they weren't set originally)
 * 4. Cleans up the WeakMap
 *
 * @see lock-elements-sizing.js for the locking mechanism
 */

(() => {
    // Check if the restore map exists
    if (!window.__elementSizingRestore) {
        console.log('⚠ Element sizing restore map not found - elements may not have been locked');
        return;
    }

    // Restore all locked dimension styles to their original state
    document.querySelectorAll('*').forEach(el => {
        const originalStyles = window.__elementSizingRestore.get(el);

        if (originalStyles) {
            const properties = ['height', 'min-height', 'max-height', 'width', 'min-width', 'max-width'];

            properties.forEach(prop => {
                const original = originalStyles[prop];

                if (original.value) {
                    // Restore original value with original priority
                    el.style.setProperty(prop, original.value, original.priority || '');
                } else {
                    // Was not set originally, so remove it
                    el.style.removeProperty(prop);
                }
            });
        }
    });

    // Clean up the global WeakMap
    delete window.__elementSizingRestore;

    console.log('✓ Element dimensions unlocked - page restored to original state');
})();
