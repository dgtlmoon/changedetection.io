/**
 * ChangeDetection.io Browser Extension - Content Script
 *
 * Handles CSS selector testing and highlighting on the active page.
 */

// Highlight class name for easy identification
const HIGHLIGHT_CLASS = 'cdio-selector-highlight';

/**
 * Remove all existing highlights from the page
 */
function clearHighlights() {
  const highlighted = document.querySelectorAll(`.${HIGHLIGHT_CLASS}`);
  highlighted.forEach(el => {
    el.classList.remove(HIGHLIGHT_CLASS);
  });
}

/**
 * Highlight elements matching a CSS selector
 * @param {string} selector - CSS selector to test
 * @returns {object} Result with count and element info
 */
function highlightSelector(selector) {
  // Clear any existing highlights
  clearHighlights();

  try {
    const elements = document.querySelectorAll(selector);

    if (elements.length === 0) {
      return { count: 0, elements: [] };
    }

    const elementInfo = [];

    elements.forEach((el, index) => {
      // Add highlight class
      el.classList.add(HIGHLIGHT_CLASS);

      // Collect element info (limit to first 20 for performance)
      if (index < 20) {
        elementInfo.push({
          tagName: el.tagName,
          id: el.id || '',
          className: el.className.replace(HIGHLIGHT_CLASS, '').trim(),
          textContent: el.textContent.trim()
        });
      }
    });

    // Scroll first match into view
    if (elements.length > 0) {
      elements[0].scrollIntoView({ behavior: 'smooth', block: 'center' });
    }

    return {
      count: elements.length,
      elements: elementInfo
    };
  } catch (error) {
    return {
      count: 0,
      elements: [],
      error: `Invalid selector: ${error.message}`
    };
  }
}

/**
 * Test a selector without highlighting (just count matches)
 * @param {string} selector - CSS selector to test
 * @returns {object} Result with count
 */
function testSelector(selector) {
  try {
    const elements = document.querySelectorAll(selector);
    return { count: elements.length };
  } catch (error) {
    return { count: 0, error: `Invalid selector: ${error.message}` };
  }
}

/**
 * Get the currently selected text and its potential CSS path
 * @returns {object} Selection info
 */
function getSelection() {
  const selection = window.getSelection();
  if (!selection.rangeCount) {
    return { text: '', element: null };
  }

  const range = selection.getRangeAt(0);
  const container = range.commonAncestorContainer;
  const element = container.nodeType === Node.TEXT_NODE
    ? container.parentElement
    : container;

  return {
    text: selection.toString(),
    element: {
      tagName: element.tagName,
      id: element.id,
      className: element.className,
      textContent: element.textContent.substring(0, 200)
    }
  };
}

/**
 * Generate a CSS selector for an element
 * @param {Element} element - DOM element
 * @returns {string} CSS selector
 */
function generateSelector(element) {
  if (!element || element === document.body) {
    return 'body';
  }

  // If element has an ID, use it
  if (element.id) {
    return `#${element.id}`;
  }

  // If element has unique classes, use them
  if (element.className && typeof element.className === 'string') {
    const classes = element.className.trim().split(/\s+/).filter(c => c && c !== HIGHLIGHT_CLASS);
    if (classes.length > 0) {
      const classSelector = `.${classes.join('.')}`;
      // Check if this selector is unique
      if (document.querySelectorAll(classSelector).length === 1) {
        return classSelector;
      }
    }
  }

  // Build path from parent
  const parent = element.parentElement;
  if (!parent) {
    return element.tagName.toLowerCase();
  }

  const parentSelector = generateSelector(parent);
  const siblings = Array.from(parent.children).filter(el => el.tagName === element.tagName);

  if (siblings.length === 1) {
    return `${parentSelector} > ${element.tagName.toLowerCase()}`;
  }

  const index = siblings.indexOf(element) + 1;
  return `${parentSelector} > ${element.tagName.toLowerCase()}:nth-child(${index})`;
}

// Listen for messages from the popup
chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
  switch (request.action) {
    case 'highlightSelector':
      sendResponse(highlightSelector(request.selector));
      break;

    case 'clearHighlights':
      clearHighlights();
      sendResponse({ success: true });
      break;

    case 'testSelector':
      sendResponse(testSelector(request.selector));
      break;

    case 'getSelection':
      sendResponse(getSelection());
      break;

    case 'generateSelector':
      // Find element at coordinates if provided
      if (request.x !== undefined && request.y !== undefined) {
        const element = document.elementFromPoint(request.x, request.y);
        if (element) {
          sendResponse({
            selector: generateSelector(element),
            element: {
              tagName: element.tagName,
              id: element.id,
              className: element.className,
              textContent: element.textContent.substring(0, 200)
            }
          });
        } else {
          sendResponse({ error: 'No element at coordinates' });
        }
      }
      break;

    default:
      sendResponse({ error: 'Unknown action' });
  }

  // Return true to indicate async response
  return true;
});

// Clear highlights when the page is about to unload
window.addEventListener('beforeunload', clearHighlights);
