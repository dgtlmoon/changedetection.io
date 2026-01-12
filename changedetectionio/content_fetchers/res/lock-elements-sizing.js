/**
 * Lock Element Dimensions for Screenshot Capture
 *
 * THE PROBLEM:
 * When taking full-page screenshots of tall pages, Chrome/Puppeteer/Playwright need to:
 * 1. Temporarily change the viewport height to a large value (e.g., 800px → 3809px)
 * 2. Take screenshots in chunks while scrolling
 * 3. Stitch the chunks together
 *
 * However, changing the viewport height triggers CSS media queries like:
 *   @media (min-height: 860px) { .ad { height: 250px; } }
 *
 * This causes elements (especially ads) to resize during screenshot capture, creating a mismatch:
 * - Screenshot shows element at NEW size (after media query triggered)
 * - xpath element coordinates measured at OLD size (before viewport change)
 * - Visual selector overlays don't align with screenshot
 *
 * EXAMPLE BUG:
 * - Initial viewport: 1280x800, ad height: 138px, article position: 279px ✓
 * - Viewport changes to 1280x3809 for screenshot
 * - Media query triggers: ad expands to 250px
 * - All content below shifts down by 112px (250-138)
 * - Article now at position: 391px (279+112)
 * - But xpath data says 279px → 112px mismatch! ✗
 *
 * THE SOLUTION:
 * Before changing viewport, lock ALL element dimensions with !important inline styles.
 * Inline styles with !important override media query CSS, preventing layout changes.
 *
 * WHAT THIS SCRIPT DOES:
 * 1. Iterates through every element on the page
 * 2. Captures current computed dimensions (width, height)
 * 3. Sets inline styles with !important to freeze those dimensions
 * 4. Disables ResizeObserver API (for JS-based resizing)
 * 5. When viewport changes for screenshot, media queries can't resize anything
 * 6. Layout remains consistent → xpath coordinates match screenshot ✓
 *
 * USAGE:
 * Execute this script BEFORE calling capture_full_page() / screenshot functions.
 * The page must be fully loaded and settled at its initial viewport size.
 * No need to restore state afterward - page is closed after screenshot.
 *
 * PERFORMANCE:
 * - Iterates all DOM elements (can be 1000s on complex pages)
 * - Typically completes in 50-200ms
 * - One-time cost before screenshot, well worth it for coordinate accuracy
 *
 * @see https://github.com/dgtlmoon/changedetection.io/issues/XXXX
 */

(() => {
    // Store original styles in a global WeakMap for later restoration
    window.__elementSizingRestore = new WeakMap();

    // Lock ALL element dimensions to prevent media query layout changes
    document.querySelectorAll('*').forEach(el => {
        const computed = window.getComputedStyle(el);
        const rect = el.getBoundingClientRect();

        // Save original inline style values BEFORE locking
        const properties = ['height', 'min-height', 'max-height', 'width', 'min-width', 'max-width'];
        const originalStyles = {};
        properties.forEach(prop => {
            originalStyles[prop] = {
                value: el.style.getPropertyValue(prop),
                priority: el.style.getPropertyPriority(prop)
            };
        });
        window.__elementSizingRestore.set(el, originalStyles);

        // Lock dimensions with !important to override media queries
        if (rect.height > 0) {
            el.style.setProperty('height', computed.height, 'important');
            el.style.setProperty('min-height', computed.height, 'important');
            el.style.setProperty('max-height', computed.height, 'important');
        }
        if (rect.width > 0) {
            el.style.setProperty('width', computed.width, 'important');
            el.style.setProperty('min-width', computed.width, 'important');
            el.style.setProperty('max-width', computed.width, 'important');
        }
    });

    // Also disable ResizeObserver for JS-based resizing
    window.ResizeObserver = class {
        constructor() {}
        observe() {}
        unobserve() {}
        disconnect() {}
    };

    console.log('✓ Element dimensions locked to prevent media query changes during screenshot');
})();
