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

    return `<br>Change comparison from <strong>${fromLabel}</strong> to <strong>${toLabel}</strong><br>Monitored via automated content change detection on public webpages. Data reflects observed text updates, not editorial verification.<br>`;
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

    // Create container with watermark background
    const container = document.createElement("div");
    container.innerHTML = `
        <div style="
            position: absolute;
            left: -9999px;
            top: 0;
            padding: 2px;
            background-color: transparent;
        ">
        <div style="
            background-color: #ffffff;
            width: ${originalElement.offsetWidth}px;
            border: 1px solid #ccc;
            border-radius: 4px;
            overflow: hidden;
        ">
            <!-- Watermark background -->
            <div style="
                position: absolute;
                top: 0;
                left: 0;
                width: 100%;
                height: 100%;
                overflow: hidden;
                pointer-events: none;
                z-index: 0;
                background-image: url(&quot;data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='400' height='200' viewBox='0 0 400 200'><g font-family='Arial' font-size='18' font-weight='700' fill='%23e8e8e8' transform='rotate(-45 200 100)'><text x='0' y='40'>changedetection.io   changedetection.io   changedetection.io</text><text x='0' y='100'>changedetection.io   changedetection.io   changedetection.io</text><text x='0' y='160'>changedetection.io   changedetection.io   changedetection.io</text></g></svg>&quot;);
                background-repeat: repeat;
                background-size: 400px 200px;
            "></div>

            <!-- Content -->
            <pre id="temp-capture-element" style="
                position: relative;
                z-index: 1;
                white-space: ${originalStyles.whiteSpace};
                font-family: ${originalStyles.fontFamily};
                font-size: ${originalStyles.fontSize};
                line-height: ${originalStyles.lineHeight};
                color: ${originalStyles.color};
                word-wrap: ${originalStyles.wordWrap};
                overflow-wrap: ${originalStyles.overflowWrap};
                background-color: transparent;
                padding: ${IMAGE_PADDING}px;
                border: ${originalStyles.border};
                box-sizing: border-box;
                margin: 0;
            "></pre>
        </div>
        </div>
    `;

    const outerWrapper = container.firstElementChild;
    const innerWrapper = outerWrapper.querySelector('div');
    const tempElement = innerWrapper.querySelector('#temp-capture-element');
    tempElement.appendChild(selectedFragment);

    // Store innerWrapper for footer appending
    outerWrapper._innerWrapper = innerWrapper;

    return outerWrapper;
}

/**
 * Count lines in a text string or document fragment
 */
function countLines(content) {
    if (!content) return 0;

    let text = '';
    if (typeof content === 'string') {
        text = content;
    } else if (content.textContent) {
        text = content.textContent;
    }

    // Count newlines + 1 (for the last line)
    const lines = text.split('\n').length;
    return lines > 0 ? lines : 1;
}

/**
 * Create footer with metadata (URL, date, version info, line count)
 */
function createFooter(selectedLines, totalLines) {
    const url = getTargetUrl();
    const date = getFormattedDate();
    const versionInfo = getVersionInfo();
    const lineInfo = (selectedLines && totalLines) ? ` - ${selectedLines} of ${totalLines} lines selected` : '';

    const footer = document.createElement("div");
    footer.innerHTML = `
        <div style="
            position: relative;
            z-index: 1;
            background-color: #1324fd;
            color: #fff;
            padding: 10px;
            margin-top: 10px;
            font-size: 12px;
            font-family: Arial, sans-serif;
            line-height: 1.5;
            border-top: 1px solid #ccc;
        ">
            Watched URL: <strong>${url}</strong><br>
            Generated at ${date}${lineInfo}
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
 * Convert data URL to Blob for sharing
 */
function dataURLtoBlob(dataURL) {
    const parts = dataURL.split(',');
    const byteString = atob(parts[1]);
    const mimeString = parts[0].split(':')[1].split(';')[0];
    const ab = new ArrayBuffer(byteString.length);
    const ia = new Uint8Array(ab);
    for (let i = 0; i < byteString.length; i++) {
        ia[i] = byteString.charCodeAt(i);
    }
    return new Blob([ab], { type: mimeString });
}

/**
 * Download the image
 */
function downloadImage(jpegDataUrl) {
    const a = document.createElement("a");
    a.href = jpegDataUrl;
    a.download = "changedetection-diff-" + Date.now() + ".jpg";
    a.click();
}

/**
 * Copy image to clipboard
 */
async function copyImageToClipboard(jpegDataUrl) {
    try {
        const blob = dataURLtoBlob(jpegDataUrl);
        await navigator.clipboard.write([
            new ClipboardItem({ 'image/jpeg': blob })
        ]);
        alert('Image copied to clipboard!');
    } catch (error) {
        console.error('Failed to copy image:', error);
        alert('Failed to copy image. Your browser may not support this feature.');
    }
}

/**
 * Share via Web Share API or fallback to platform-specific sharing
 */
async function shareImage(platform, jpegDataUrl) {
    const url = getTargetUrl();
    const shareText = `Check out this change detected on ${url} via changedetection.io`;
    const filename = "changedetection-diff-" + Date.now() + ".jpg";

    // Try Web Share API first (works on mobile and some desktop browsers)
    if (platform === 'native' && navigator.share) {
        try {
            const blob = dataURLtoBlob(jpegDataUrl);
            const file = new File([blob], filename, { type: 'image/jpeg' });

            await navigator.share({
                title: 'Change Detection Diff',
                text: shareText,
                files: [file]
            });
            return;
        } catch (error) {
            if (error.name !== 'AbortError') {
                console.error('Web Share API failed:', error);
            }
            return;
        }
    }

    // Platform-specific fallbacks
    const encodedText = encodeURIComponent(shareText);
    const encodedUrl = encodeURIComponent(url);

    let shareUrl;
    switch (platform) {
        case 'twitter':
            shareUrl = `https://twitter.com/intent/tweet?text=${encodedText}`;
            break;
        case 'facebook':
            shareUrl = `https://www.facebook.com/sharer/sharer.php?u=${encodedUrl}&quote=${encodedText}`;
            break;
        case 'linkedin':
            shareUrl = `https://www.linkedin.com/sharing/share-offsite/?url=${encodedUrl}`;
            break;
        case 'reddit':
            shareUrl = `https://reddit.com/submit?url=${encodedUrl}&title=${encodeURIComponent('Change Detection Diff')}`;
            break;
        case 'email':
            shareUrl = `mailto:?subject=${encodeURIComponent('Change Detection Diff')}&body=${encodedText}`;
            break;
        default:
            return;
    }

    window.open(shareUrl, '_blank', 'width=600,height=400');
}

/**
 * Display or download the generated image
 */
function displayImage(jpegDataUrl) {
    const win = window.open();
    if (win) {
        win.document.write(`
            <html>
                <head>
                    <title>Diff Screenshot</title>
                    <style>
                        body {
                            margin: 0;
                            padding: 20px;
                            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Arial, sans-serif;
                            background: #f5f5f5;
                        }
                        .container {
                            max-width: 1200px;
                            margin: 0 auto;
                            background: white;
                            padding: 20px;
                            border-radius: 8px;
                            box-shadow: 0 2px 8px rgba(0,0,0,0.1);
                        }
                        img {
                            max-width: 100%;
                            display: block;
                            margin-bottom: 20px;
                            border: 1px solid #ddd;
                            border-radius: 4px;
                        }
                        .share-section {
                            padding: 20px 0;
                            border-top: 2px solid #e0e0e0;
                        }
                        .share-section h3 {
                            margin: 0 0 15px 0;
                            color: #333;
                            font-size: 18px;
                        }
                        .share-buttons {
                            display: flex;
                            flex-wrap: wrap;
                            gap: 10px;
                        }
                        .share-btn {
                            padding: 10px 20px;
                            border: none;
                            border-radius: 6px;
                            font-size: 14px;
                            font-weight: 600;
                            cursor: pointer;
                            transition: all 0.2s;
                            text-decoration: none;
                            display: inline-flex;
                            align-items: center;
                            gap: 8px;
                        }
                        .share-btn:hover {
                            transform: translateY(-2px);
                            box-shadow: 0 4px 12px rgba(0,0,0,0.15);
                        }
                        .btn-download {
                            background: #4CAF50;
                            color: white;
                        }
                        .btn-native {
                            background: #2196F3;
                            color: white;
                        }
                        .btn-twitter {
                            background: #000000;
                            color: white;
                        }
                        .btn-facebook {
                            background: #1877F2;
                            color: white;
                        }
                        .btn-linkedin {
                            background: #0A66C2;
                            color: white;
                        }
                        .btn-reddit {
                            background: #FF4500;
                            color: white;
                        }
                        .btn-email {
                            background: #757575;
                            color: white;
                        }
                    </style>
                </head>
                <body>
                    <div class="container">
                        <img src="${jpegDataUrl}" alt="Diff Screenshot" id="diffImage"/>

                        <div class="share-section">
                            <h3>Share or Download</h3>
                            <p style="margin: 0 0 15px 0; padding: 12px; background: #f0f7ff; border-left: 4px solid #2196F3; color: #333; font-size: 14px; line-height: 1.5;">
                                <strong>💡 Tip:</strong> Right-click the image above and select "Copy Image", then click a share button below and paste it into your post (Ctrl+V or right-click → Paste).
                            </p>
                            <div class="share-buttons">
                                <button class="share-btn btn-download" onclick="downloadImage()">
                                    📥 Download Image
                                </button>
                                ${navigator.share ? '<button class="share-btn btn-native" onclick="shareNative()">📤 Share...</button>' : ''}
                                <button class="share-btn btn-twitter" onclick="shareToTwitter()">
                                    𝕏 Share to X
                                </button>
                                <button class="share-btn btn-facebook" onclick="shareToFacebook()">
                                    Share to Facebook
                                </button>
                                <button class="share-btn btn-linkedin" onclick="shareToLinkedIn()">
                                    Share to LinkedIn
                                </button>
                                <button class="share-btn btn-reddit" onclick="shareToReddit()">
                                    Share to Reddit
                                </button>
                                <button class="share-btn btn-email" onclick="shareViaEmail()">
                                    📧 Share via Email
                                </button>
                            </div>
                        </div>
                    </div>

                    <script>
                        const imageDataUrl = "${jpegDataUrl}";

                        function dataURLtoBlob(dataURL) {
                            const parts = dataURL.split(',');
                            const byteString = atob(parts[1]);
                            const mimeString = parts[0].split(':')[1].split(';')[0];
                            const ab = new ArrayBuffer(byteString.length);
                            const ia = new Uint8Array(ab);
                            for (let i = 0; i < byteString.length; i++) {
                                ia[i] = byteString.charCodeAt(i);
                            }
                            return new Blob([ab], { type: mimeString });
                        }

                        function downloadImage() {
                            const a = document.createElement("a");
                            a.href = imageDataUrl;
                            a.download = "changedetection-diff-" + Date.now() + ".jpg";
                            a.click();
                        }

                        async function shareNative() {
                            try {
                                const blob = dataURLtoBlob(imageDataUrl);
                                const file = new File([blob], "changedetection-diff-" + Date.now() + ".jpg", { type: 'image/jpeg' });
                                await navigator.share({
                                    title: 'Change Detection Diff',
                                    text: 'Check out this change detected via changedetection.io',
                                    files: [file]
                                });
                            } catch (error) {
                                if (error.name !== 'AbortError') {
                                    console.error('Share failed:', error);
                                }
                            }
                        }

                        function shareToTwitter() {
                            const text = encodeURIComponent('Check out this change detected via changedetection.io');
                            window.open('https://twitter.com/intent/tweet?text=' + text, '_blank', 'width=600,height=400');
                        }

                        function shareToFacebook() {
                            const cdUrl = encodeURIComponent('https://changedetection.io');
                            window.open('https://www.facebook.com/sharer/sharer.php?u=' + cdUrl, '_blank', 'width=600,height=400');
                        }

                        function shareToLinkedIn() {
                            const cdUrl = encodeURIComponent('https://changedetection.io');
                            window.open('https://www.linkedin.com/sharing/share-offsite/?url=' + cdUrl, '_blank', 'width=600,height=400');
                        }

                        function shareToReddit() {
                            const cdUrl = encodeURIComponent('https://changedetection.io');
                            const title = encodeURIComponent('Change Detection Tool');
                            window.open('https://reddit.com/submit?url=' + cdUrl + '&title=' + title, '_blank', 'width=600,height=400');
                        }

                        function shareViaEmail() {
                            const subject = encodeURIComponent('Change Detection Diff');
                            const body = encodeURIComponent('Check out this change detected via changedetection.io');
                            window.location.href = 'mailto:?subject=' + subject + '&body=' + body;
                        }
                    </script>
                </body>
            </html>
        `);
    } else {
        // Fallback: trigger download if popup is blocked
        const a = document.createElement("a");
        a.href = jpegDataUrl;
        a.download = "changedetection-diff-" + Date.now() + ".jpg";
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

        // Count lines for footer
        const selectedLines = countLines(selectedFragment);
        const totalLines = countLines(differenceElement);

        // Create temporary element with proper styling
        tempElement = createCaptureElement(selectedFragment, differenceElement);
        // Append footer to innerWrapper (inside the border), not outerWrapper
        tempElement._innerWrapper.appendChild(createFooter(selectedLines, totalLines));

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
