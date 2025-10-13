/**
 * snippet-to-image.js
 * Converts selected diff content to a shareable JPEG image with metadata
 */

// Constants
const IMAGE_PADDING = 5;
const JPEG_QUALITY = 0.95;
const CANVAS_SCALE = 1;
const RENDER_DELAY_MS = 50;

/**
 * Utility: Get the target URL from global watch_url or fallback to current URL
 */
function getTargetUrl() {
    return (typeof watch_url !== 'undefined' && watch_url) ? watch_url : window.location.href;
}

/**
 * Utility: Get formatted current date with timezone
 */
function getFormattedDate() {
    return new Date().toLocaleString(undefined, {
        year: 'numeric',
        month: 'long',
        day: 'numeric',
        hour: '2-digit',
        minute: '2-digit',
        second: '2-digit',
        timeZoneName: 'short'
    });
}

/**
 * Utility: Get version comparison info from the diff selectors
 */
function getVersionInfo() {
    const fromSelect = document.getElementById('diff-version');
    const toSelect = document.getElementById('current-version');

    if (!fromSelect || !toSelect) {
        return '';
    }

    const fromOption = fromSelect.options[fromSelect.selectedIndex];
    const toOption = toSelect.options[toSelect.selectedIndex];
    const fromLabel = fromOption ? (fromOption.getAttribute('label') || fromOption.text) : 'Unknown';
    const toLabel = toOption ? (toOption.getAttribute('label') || toOption.text) : 'Unknown';

    return `<br>Change comparison from <strong>${fromLabel}</strong> to <strong>${toLabel}</strong>`;
}

/**
 * Helper: Find text node containing newline in a given direction
 */
function findTextNodeWithNewline(node, searchBackwards = false) {
    if (node.nodeType === Node.TEXT_NODE) {
        const text = node.textContent;
        const idx = searchBackwards ? text.lastIndexOf('\n') : text.indexOf('\n');
        if (idx !== -1) {
            return { node, offset: searchBackwards ? idx + 1 : idx };
        }
    } else {
        const walker = document.createTreeWalker(node, NodeFilter.SHOW_TEXT);
        let textNode;
        while (textNode = walker.nextNode()) {
            const text = textNode.textContent;
            const idx = searchBackwards ? text.lastIndexOf('\n') : text.indexOf('\n');
            if (idx !== -1) {
                return { node: textNode, offset: searchBackwards ? idx + 1 : idx };
            }
        }
    }
    return null;
}

/**
 * Helper: Walk through siblings in a given direction to find line boundary
 */
function findLineBoundary(node, container, searchBackwards = false) {
    let currentNode = node;

    while (currentNode && currentNode !== container) {
        const sibling = searchBackwards ? currentNode.previousSibling : currentNode.nextSibling;
        let currentSibling = sibling;

        while (currentSibling) {
            const result = findTextNodeWithNewline(currentSibling, searchBackwards);
            if (result) {
                return result;
            }
            currentSibling = searchBackwards ? currentSibling.previousSibling : currentSibling.nextSibling;
        }

        currentNode = currentNode.parentNode;
    }

    return null;
}

/**
 * Helper: Get the last text node in a container
 */
function getLastTextNode(container) {
    const walker = document.createTreeWalker(container, NodeFilter.SHOW_TEXT);
    let lastNode = null;
    let textNode;
    while (textNode = walker.nextNode()) {
        lastNode = textNode;
    }
    return lastNode;
}

/**
 * Expands a selection range to include complete lines
 * If a user selects partial text, this ensures full lines are captured
 */
function expandRangeToFullLines(range, container) {
    const newRange = range.cloneRange();

    // Expand start to line beginning
    if (newRange.startContainer.nodeType === Node.TEXT_NODE) {
        const text = newRange.startContainer.textContent;
        const lastNewline = text.lastIndexOf('\n', newRange.startOffset - 1);
        if (lastNewline !== -1) {
            newRange.setStart(newRange.startContainer, lastNewline + 1);
        } else {
            const lineStart = findLineBoundary(newRange.startContainer, container, true);
            if (lineStart) {
                newRange.setStart(lineStart.node, lineStart.offset);
            } else {
                newRange.setStart(container, 0);
            }
        }
    }

    // Expand end to line end
    if (newRange.endContainer.nodeType === Node.TEXT_NODE) {
        const text = newRange.endContainer.textContent;
        const nextNewline = text.indexOf('\n', newRange.endOffset);
        if (nextNewline !== -1) {
            newRange.setEnd(newRange.endContainer, nextNewline);
        } else {
            const lineEnd = findLineBoundary(newRange.endContainer, container, false);
            if (lineEnd) {
                newRange.setEnd(lineEnd.node, lineEnd.offset);
            } else {
                const lastNode = getLastTextNode(container);
                newRange.setEnd(
                    lastNode || container,
                    lastNode ? lastNode.textContent.length : container.childNodes.length
                );
            }
        }
    }

    return newRange;
}

/**
 * Create a temporary element with the selected content styled for capture
 */
function createCaptureElement(selectedFragment, originalElement) {
    const originalStyles = window.getComputedStyle(originalElement);

    // Create wrapper container
    const wrapper = document.createElement("div");
    wrapper.innerHTML = `
        <pre id="temp-capture-element" style="
            position: absolute;
            left: -9999px;
            top: 0;
            white-space: ${originalStyles.whiteSpace};
            font-family: ${originalStyles.fontFamily};
            font-size: ${originalStyles.fontSize};
            line-height: ${originalStyles.lineHeight};
            color: ${originalStyles.color};
            word-wrap: ${originalStyles.wordWrap};
            overflow-wrap: ${originalStyles.overflowWrap};
            background-color: #ffffff;
            padding: ${IMAGE_PADDING}px;
            border: ${originalStyles.border};
            box-sizing: border-box;
            width: ${originalElement.offsetWidth}px;
        "></pre>
    `;

    const tempElement = wrapper.firstElementChild;
    tempElement.appendChild(selectedFragment);

    return tempElement;
}

/**
 * Create footer with metadata (URL, date, version info)
 */
function createFooter() {
    const url = getTargetUrl();
    const date = getFormattedDate();
    const versionInfo = getVersionInfo();

    const footer = document.createElement("div");
    footer.innerHTML = `
        <div style="
            background-color: #eee;
            color: #222;
            padding: 10px;
            margin-top: 10px;
            font-size: 12px;
            font-family: Arial, sans-serif;
            line-height: 1.5;
            border-top: 1px solid #ccc;
        ">
            <strong>${url}</strong><br>
            Generated by changedetection.io at ${date}
            ${versionInfo}
        </div>
    `;

    return footer.firstElementChild;
}

/**
 * Add EXIF metadata to JPEG image
 */
function addExifMetadata(jpegDataUrl) {
    if (typeof piexif === 'undefined') {
        return jpegDataUrl;
    }

    try {
        const url = getTargetUrl();
        const timestamp = new Date().toISOString();

        const exifObj = {
            "0th": {
                [piexif.ImageIFD.Software]: "changedetection.io",
                [piexif.ImageIFD.ImageDescription]: `Diff snapshot from ${url}`,
                [piexif.ImageIFD.Copyright]: "Generated by changedetection.io"
            },
            "Exif": {
                [piexif.ExifIFD.DateTimeOriginal]: timestamp,
                [piexif.ExifIFD.UserComment]: `URL: ${url} | Captured: ${timestamp} | Source: changedetection.io`
            }
        };

        const exifBytes = piexif.dump(exifObj);
        return piexif.insert(exifBytes, jpegDataUrl);
    } catch (error) {
        console.warn("Failed to add EXIF metadata:", error);
        return jpegDataUrl;
    }
}

/**
 * Display or download the generated image
 */
function displayImage(jpegDataUrl) {
    const win = window.open();
    if (win) {
        win.document.write(`
            <html>
                <head><title>Diff Screenshot</title></head>
                <body style="margin:0;">
                    <img src="${jpegDataUrl}" alt="Diff Screenshot" style="max-width:100%;"/>
                </body>
            </html>
        `);
    } else {
        // Fallback: trigger download if popup is blocked
        const a = document.createElement("a");
        a.href = jpegDataUrl;
        a.download = "diff-snapshot-" + Date.now() + ".jpg";
        a.click();
    }
}

/**
 * Update button UI state
 */
function setButtonState(button, isLoading, originalHtml = '') {
    if (!button) return;

    if (isLoading) {
        button.innerHTML = 'Generating...';
        button.style.opacity = "0.5";
        button.style.pointerEvents = "none";
    } else {
        button.innerHTML = originalHtml;
        button.style.opacity = "1";
        button.style.pointerEvents = "auto";
    }
}

/**
 * Main function: Convert selected diff text to a shareable JPEG image
 *
 * Features:
 * - Expands partial selections to full lines
 * - Preserves all diff highlighting and formatting
 * - Adds metadata footer with URL and version info
 * - Embeds EXIF metadata in the JPEG
 * - Opens in new window or downloads if popup blocked
 */
async function diffToJpeg() {
    // Validate dependencies
    if (typeof html2canvas === 'undefined') {
        alert("html2canvas library is not loaded yet. Please wait a moment and try again.");
        return;
    }

    // Validate selection
    const selection = window.getSelection();
    if (!selection || selection.rangeCount === 0 || selection.isCollapsed) {
        alert("Please select the text/lines you want to capture first by highlighting with your mouse.");
        return;
    }

    const originalRange = selection.getRangeAt(0);
    const differenceElement = document.getElementById("difference");

    if (!differenceElement || !differenceElement.contains(originalRange.commonAncestorContainer)) {
        alert("Please select text within the diff content.");
        return;
    }

    // Setup UI state
    const btn = document.getElementById("share-as-image-btn");
    const originalBtnHtml = btn ? btn.innerHTML : '';
    setButtonState(btn, true);

    let tempElement = null;

    try {
        // Expand selection to full lines and clone content
        const expandedRange = expandRangeToFullLines(originalRange, differenceElement);
        const selectedFragment = expandedRange.cloneContents();

        // Create temporary element with proper styling
        tempElement = createCaptureElement(selectedFragment, differenceElement);
        tempElement.appendChild(createFooter());

        // Add to DOM for rendering
        document.body.appendChild(tempElement);

        // Wait for rendering
        await new Promise(resolve => setTimeout(resolve, RENDER_DELAY_MS));

        // Capture to canvas
        const canvas = await html2canvas(tempElement, {
            scale: CANVAS_SCALE,
            useCORS: true,
            allowTaint: true,
            logging: false,
            backgroundColor: '#ffffff',
            scrollX: 0,
            scrollY: 0
        });

        // Validate canvas
        if (canvas.width === 0 || canvas.height === 0) {
            throw new Error("Canvas is empty - no content captured");
        }

        // Convert to JPEG
        let jpeg = canvas.toDataURL("image/jpeg", JPEG_QUALITY);

        if (jpeg === "data:," || jpeg.length < 100) {
            throw new Error("Failed to generate image data");
        }

        // Add EXIF metadata
        jpeg = addExifMetadata(jpeg);

        // Display the image
        displayImage(jpeg);

        // Clear selection
        selection.removeAllRanges();

    } catch (error) {
        console.error("Error generating image:", error);
        alert("Failed to generate image: " + error.message);
    } finally {
        // Cleanup
        if (tempElement && tempElement.parentNode) {
            tempElement.parentNode.removeChild(tempElement);
        }
        setButtonState(btn, false, originalBtnHtml);
    }
}
