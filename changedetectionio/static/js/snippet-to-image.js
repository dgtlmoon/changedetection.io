/**
 * snippet-to-image.js
 * Converts the selected diff content to a JPEG image for sharing/downloading
 */

async function diffToJpeg() {
    // Check if html2canvas is loaded
    if (typeof html2canvas === 'undefined') {
        alert("html2canvas library is not loaded yet. Please wait a moment and try again.");
        return;
    }

    // Get the user's text selection
    const selection = window.getSelection();
    if (!selection || selection.rangeCount === 0 || selection.isCollapsed) {
        alert("Please select the text/lines you want to capture first by highlighting with your mouse.");
        return;
    }

    // Show a loading indicator
    const btn = document.getElementById("share-as-image-btn");
    const originalText = btn ? btn.innerHTML : '';
    if (btn) {
        btn.innerHTML = 'Generating...';
        btn.style.opacity = "0.5";
        btn.style.pointerEvents = "none";
    }

    let tempElement = null;

    try {
        // Get the selected content with HTML (preserves spans and styling)
        const range = selection.getRangeAt(0);
        const selectedFragment = range.cloneContents();

        // Create a temporary element to hold the selected content
        tempElement = document.createElement("pre");
        tempElement.id = "temp-capture-element";
        tempElement.appendChild(selectedFragment);

        // Copy styles from the original #difference element
        const originalPre = document.getElementById("difference");
        const originalStyles = window.getComputedStyle(originalPre);

        tempElement.style.position = "absolute";
        tempElement.style.left = "-9999px";
        tempElement.style.top = "0";
        tempElement.style.whiteSpace = "pre-wrap";
        tempElement.style.fontFamily = originalStyles.fontFamily;
        tempElement.style.fontSize = originalStyles.fontSize;
        tempElement.style.lineHeight = originalStyles.lineHeight;
        tempElement.style.color = originalStyles.color;
        tempElement.style.backgroundColor = "#ffffff";
        tempElement.style.padding = "10px";
        tempElement.style.border = originalStyles.border;
        tempElement.style.width = "auto";
        tempElement.style.maxWidth = originalPre.offsetWidth + "px";

        // Add to document so it can be measured and captured
        document.body.appendChild(tempElement);

        console.log("Capturing selection...");
        console.log("Temp element dimensions:", tempElement.offsetWidth, "x", tempElement.offsetHeight);

        // Give browser time to render
        await new Promise(resolve => setTimeout(resolve, 50));

        const canvas = await html2canvas(tempElement, {
            scale: 2,                          // higher quality
            useCORS: true,
            allowTaint: true,
            logging: false,
            backgroundColor: '#ffffff',
            scrollX: 0,
            scrollY: 0
        });

        console.log("Canvas created:", canvas.width, "x", canvas.height);

        if (canvas.width === 0 || canvas.height === 0) {
            throw new Error("Canvas is empty - no content captured");
        }

        // Convert to JPEG
        const jpeg = canvas.toDataURL("image/jpeg", 0.95);

        if (jpeg === "data:," || jpeg.length < 100) {
            throw new Error("Failed to generate image data");
        }

        // Open in new window
        const win = window.open();
        if (win) {
            win.document.write('<html><head><title>Diff Screenshot</title></head><body style="margin:0;"><img src="' + jpeg + '" alt="Diff Screenshot" style="max-width:100%;"/></body></html>');
        } else {
            // Fallback to download if popup blocked
            const a = document.createElement("a");
            a.href = jpeg;
            a.download = "diff-snapshot-" + Date.now() + ".jpg";
            a.click();
        }

        // Clear the selection
        selection.removeAllRanges();

    } catch (error) {
        console.error("Error generating image:", error);
        alert("Failed to generate image: " + error.message);
    } finally {
        // Clean up temporary element
        if (tempElement && tempElement.parentNode) {
            tempElement.parentNode.removeChild(tempElement);
        }

        // Reset button state
        if (btn) {
            btn.innerHTML = originalText;
            btn.style.opacity = "1";
            btn.style.pointerEvents = "auto";
        }
    }
}
