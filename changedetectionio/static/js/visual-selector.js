// Copyright (C) 2021 Leigh Morresi (dgtlmoon@gmail.com)
// All rights reserved.
// yes - this is really a hack, if you are a front-ender and want to help, please get in touch!

let runInClearMode = false;

$(document).ready(() => {
    let currentSelections = [];
    let currentSelection = null;
    let appendToList = false;
    let c, xctx, ctx;
    let xScale = 1, yScale = 1;
    let selectorImage, selectorImageRect, selectorData;
    let elementHandlers = {}; // Store references to element selection handlers (needed for draw mode toggling)

    // Box drawing mode variables (for image_ssim_diff processor)
    let drawMode = false;
    let isDrawing = false;
    let isDragging = false;
    let drawStartX, drawStartY;
    let dragOffsetX, dragOffsetY;
    let drawnBox = null;
    let resizeHandle = null;
    const HANDLE_SIZE = 8;
    const isImageProcessor = $('input[value="image_ssim_diff"]').is(':checked');


    // Global jQuery selectors with "Elem" appended
    const $selectorCanvasElem = $('#selector-canvas');
    const $includeFiltersElem = $("#include_filters");
    const $selectorBackgroundElem = $("img#selector-background");
    const $selectorCurrentXpathElem = $("#selector-current-xpath span");
    const $fetchingUpdateNoticeElem = $('.fetching-update-notice');
    const $selectorWrapperElem = $("#selector-wrapper");

    // Color constants
    const FILL_STYLE_HIGHLIGHT = 'rgba(205,0,0,0.35)';
    const FILL_STYLE_GREYED_OUT = 'rgba(205,205,205,0.95)';
    const STROKE_STYLE_HIGHLIGHT = 'rgba(255,0,0, 0.9)';
    const FILL_STYLE_REDLINE = 'rgba(255,0,0, 0.1)';
    const STROKE_STYLE_REDLINE = 'rgba(225,0,0,0.9)';

    $('#visualselector-tab').click(() => {
        $selectorBackgroundElem.off('load');
        currentSelections = [];
        bootstrapVisualSelector();
    });

    function clearReset() {
        ctx.clearRect(0, 0, c.width, c.height);

        if ($includeFiltersElem.val().length) {
            alert("Existing filters under the 'Filters & Triggers' tab were cleared.");
        }
        $includeFiltersElem.val('');

        currentSelections = [];

        // Means we ignore the xpaths from the scraper marked as sel.highlight_as_custom_filter (it matched a previous selector)
        runInClearMode = true;

        highlightCurrentSelected();
    }

    function splitToList(v) {
        return v.split('\n').map(line => line.trim()).filter(line => line.length > 0);
    }

    function sortScrapedElementsBySize() {
        // Sort the currentSelections array by area (width * height) in descending order
        selectorData['size_pos'].sort((a, b) => {
            const areaA = a.width * a.height;
            const areaB = b.width * b.height;
            return areaB - areaA;
        });
    }

    $(document).on('keydown keyup', (event) => {
        if (event.code === 'ShiftLeft' || event.code === 'ShiftRight') {
            appendToList = event.type === 'keydown';
        }

        if (event.type === 'keydown') {
            if ($selectorBackgroundElem.is(":visible") && event.key === "Escape") {
                clearReset();
            }
        }
    });

    $('#clear-selector').on('click', () => {
        clearReset();
    });
    // So if they start switching between visualSelector and manual filters, stop it from rendering old filters
    $('li.tab a').on('click', () => {
        runInClearMode = true;
    });

    if (!window.location.hash || window.location.hash !== '#visualselector') {
        $selectorBackgroundElem.attr('src', '');
        return;
    }

    bootstrapVisualSelector();

    function bootstrapVisualSelector() {
        $selectorBackgroundElem
            .on("error", () => {
                $fetchingUpdateNoticeElem.html("<strong>Ooops!</strong> The VisualSelector tool needs at least one fetched page, please unpause the watch and/or wait for the watch to complete fetching and then reload this page.")
                    .css('color', '#bb0000');
                $('#selector-current-xpath, #clear-selector').hide();
            })
            .on('load', () => {
                console.log("Loaded background...");
                c = document.getElementById("selector-canvas");
                xctx = c.getContext("2d");
                ctx = c.getContext("2d");
                fetchData();
                $selectorCanvasElem.off("mousemove mousedown");
            })
            .attr("src", screenshot_url);

        let s = `${$selectorBackgroundElem.attr('src')}?${new Date().getTime()}`;
        $selectorBackgroundElem.attr('src', s);
    }

    function alertIfFilterNotFound() {
        let existingFilters = splitToList($includeFiltersElem.val());
        let sizePosXpaths = selectorData['size_pos'].map(sel => sel.xpath);

        for (let filter of existingFilters) {
            if (!sizePosXpaths.includes(filter)) {
                alert(`One or more of your existing filters was not found and will be removed when a new filter is selected.`);
                break;
            }
        }
    }

    function fetchData() {
        $fetchingUpdateNoticeElem.html("Fetching element data..");

        $.ajax({
            url: watch_visual_selector_data_url,
            context: document.body
        }).done((data) => {
            $fetchingUpdateNoticeElem.html("Rendering..");
            selectorData = data;

            sortScrapedElementsBySize();
            console.log(`Reported browser width from backend: ${data['browser_width']}`);

            // Little sanity check for the user, alert them if something missing
            alertIfFilterNotFound();

            setScale();
            reflowSelector();

            // Initialize draw mode after everything is set up
            initializeDrawMode();

            $fetchingUpdateNoticeElem.fadeOut();
        });
    }

    function updateFiltersText() {
        // Assuming currentSelections is already defined and contains the selections
        let uniqueSelections = new Set(currentSelections.map(sel => (sel[0] === '/' ? `xpath:${sel.xpath}` : sel.xpath)));

        if (currentSelections.length > 0) {
            // Convert the Set back to an array and join with newline characters
            let textboxFilterText = Array.from(uniqueSelections).join("\n");
            $includeFiltersElem.val(textboxFilterText);
        }
    }

    function setScale() {
        $selectorWrapperElem.show();
        selectorImage = $selectorBackgroundElem[0];
        selectorImageRect = selectorImage.getBoundingClientRect();

        $selectorCanvasElem.attr({
            'height': selectorImageRect.height,
            'width': selectorImageRect.width
        });
        $selectorWrapperElem.attr('width', selectorImageRect.width);
        $('#visual-selector-heading').css('max-width', selectorImageRect.width + "px")

        xScale = selectorImageRect.width / selectorImage.naturalWidth;
        yScale = selectorImageRect.height / selectorImage.naturalHeight;

        ctx.strokeStyle = STROKE_STYLE_HIGHLIGHT;
        ctx.fillStyle = FILL_STYLE_REDLINE;
        ctx.lineWidth = 3;
        console.log("Scaling set  x: " + xScale + " by y:" + yScale);
        $("#selector-current-xpath").css('max-width', selectorImageRect.width);
    }

    function reflowSelector() {
        $(window).resize(() => {
            setScale();
            highlightCurrentSelected();
        });

        setScale();

        console.log(selectorData['size_pos'].length + " selectors found");

        let existingFilters = splitToList($includeFiltersElem.val());

        selectorData['size_pos'].forEach(sel => {
            if ((!runInClearMode && sel.highlight_as_custom_filter) || existingFilters.includes(sel.xpath)) {
                console.log("highlighting " + c);
                currentSelections.push(sel);
            }
        });


        highlightCurrentSelected();
        updateFiltersText();

        // Store handler references for later use
        elementHandlers.handleMouseMove = handleMouseMove.debounce(5);
        elementHandlers.handleMouseDown = handleMouseDown.debounce(5);
        elementHandlers.handleMouseLeave = highlightCurrentSelected.debounce(5);

        $selectorCanvasElem.bind('mousemove', elementHandlers.handleMouseMove);
        $selectorCanvasElem.bind('mousedown', elementHandlers.handleMouseDown);
        $selectorCanvasElem.bind('mouseleave', elementHandlers.handleMouseLeave);

        function handleMouseMove(e) {
            if (!e.offsetX && !e.offsetY) {
                const targetOffset = $(e.target).offset();
                e.offsetX = e.pageX - targetOffset.left;
                e.offsetY = e.pageY - targetOffset.top;
            }

            ctx.fillStyle = FILL_STYLE_HIGHLIGHT;

            selectorData['size_pos'].forEach(sel => {
                if (e.offsetY > sel.top * yScale && e.offsetY < sel.top * yScale + sel.height * yScale &&
                    e.offsetX > sel.left * yScale && e.offsetX < sel.left * yScale + sel.width * yScale) {
                    setCurrentSelectedText(sel.xpath);
                    drawHighlight(sel);
                    currentSelections.push(sel);
                    currentSelection = sel;
                    highlightCurrentSelected();
                    currentSelections.pop();
                }
            })
        }


        function setCurrentSelectedText(s) {
            $selectorCurrentXpathElem[0].innerHTML = s;
        }

        function drawHighlight(sel) {
            ctx.strokeRect(sel.left * xScale, sel.top * yScale, sel.width * xScale, sel.height * yScale);
            ctx.fillRect(sel.left * xScale, sel.top * yScale, sel.width * xScale, sel.height * yScale);
        }

        function handleMouseDown() {
            // If we are in 'appendToList' mode, grow the list, if not, just 1
            currentSelections = appendToList ? [...currentSelections, currentSelection] : [currentSelection];
            highlightCurrentSelected();
            updateFiltersText();
        }

    }

    function highlightCurrentSelected() {
        xctx.fillStyle = FILL_STYLE_GREYED_OUT;
        xctx.strokeStyle = STROKE_STYLE_REDLINE;
        xctx.lineWidth = 3;
        xctx.clearRect(0, 0, c.width, c.height);

        currentSelections.forEach(sel => {
            //xctx.clearRect(sel.left * xScale, sel.top * yScale, sel.width * xScale, sel.height * yScale);
            xctx.strokeRect(sel.left * xScale, sel.top * yScale, sel.width * xScale, sel.height * yScale);
        });
    }

    // ============= BOX DRAWING MODE (for image_ssim_diff processor) =============

    function initializeDrawMode() {
        if (!isImageProcessor || !c) return;

        const $selectorModeRadios = $('input[name="selector-mode"]');
        const $boundingBoxField = $('#bounding_box');
        const $selectionModeField = $('#selection_mode');

        // Load existing selection mode if present
        const savedMode = $selectionModeField.val();
        if (savedMode && (savedMode === 'element' || savedMode === 'draw')) {
            $selectorModeRadios.filter(`[value="${savedMode}"]`).prop('checked', true);
            console.log('Loaded saved mode:', savedMode);
        }

        // Load existing bounding box if present
        const existingBox = $boundingBoxField.val();
        if (existingBox) {
            try {
                const parts = existingBox.split(',').map(p => parseFloat(p));
                if (parts.length === 4) {
                    drawnBox = {
                        x: parts[0] * xScale,
                        y: parts[1] * yScale,
                        width: parts[2] * xScale,
                        height: parts[3] * yScale
                    };
                    console.log('Loaded saved bounding box:', existingBox);
                }
            } catch (e) {
                console.error('Failed to parse existing bounding box:', e);
            }
        }

        // Update mode when radio changes
        $selectorModeRadios.off('change').on('change', function() {
            const newMode = $(this).val();
            drawMode = newMode === 'draw';
            console.log('Mode changed to:', newMode);

            // Save the mode to the hidden field
            $selectionModeField.val(newMode);

            if (drawMode) {
                enableDrawMode();
            } else {
                disableDrawMode();
            }
        });

        // Set initial mode based on which radio is checked
        drawMode = $selectorModeRadios.filter(':checked').val() === 'draw';
        console.log('Initial mode:', drawMode ? 'draw' : 'element');

        // Save initial mode
        $selectionModeField.val(drawMode ? 'draw' : 'element');

        if (drawMode) {
            enableDrawMode();
        }
    }

    function enableDrawMode() {
        console.log('Enabling draw mode...');

        // Unbind element selection handlers
        $selectorCanvasElem.unbind('mousemove mousedown mouseleave');

        // Set cursor to crosshair
        $selectorCanvasElem.css('cursor', 'crosshair');

        // Bind draw mode handlers
        $selectorCanvasElem.on('mousedown', handleDrawMouseDown);
        $selectorCanvasElem.on('mousemove', handleDrawMouseMove);
        $selectorCanvasElem.on('mouseup', handleDrawMouseUp);
        $selectorCanvasElem.on('mouseleave', handleDrawMouseUp);

        // Clear element selections and xpath display
        currentSelections = [];
        $includeFiltersElem.val('');
        $selectorCurrentXpathElem.html('Draw mode - click and drag to select an area');

        // Clear the canvas
        if (ctx && xctx) {
            ctx.clearRect(0, 0, c.width, c.height);
            xctx.clearRect(0, 0, c.width, c.height);
        }

        // Redraw if we have an existing box
        if (drawnBox) {
            drawBox();
        }
    }

    function disableDrawMode() {
        console.log('Disabling draw mode, switching to element mode...');

        // Unbind draw handlers
        $selectorCanvasElem.unbind('mousedown mousemove mouseup mouseleave');

        // Reset cursor
        $selectorCanvasElem.css('cursor', 'default');

        // Clear drawn box
        drawnBox = null;
        $('#bounding_box').val('');

        // Clear the canvases
        if (ctx && xctx) {
            ctx.clearRect(0, 0, c.width, c.height);
            xctx.clearRect(0, 0, c.width, c.height);
        }

        // Restore element selections from include_filters
        currentSelections = [];
        if (selectorData && selectorData['size_pos']) {
            let existingFilters = splitToList($includeFiltersElem.val());

            selectorData['size_pos'].forEach(sel => {
                if ((!runInClearMode && sel.highlight_as_custom_filter) || existingFilters.includes(sel.xpath)) {
                    console.log("Restoring selection: " + sel.xpath);
                    currentSelections.push(sel);
                }
            });
        }

        // Re-enable element selection handlers using stored references
        if (elementHandlers.handleMouseMove) {
            $selectorCanvasElem.bind('mousemove', elementHandlers.handleMouseMove);
            $selectorCanvasElem.bind('mousedown', elementHandlers.handleMouseDown);
            $selectorCanvasElem.bind('mouseleave', elementHandlers.handleMouseLeave);
        }

        // Restore the element selection display
        $selectorCurrentXpathElem.html('Hover over elements to select');

        // Highlight the restored selections
        highlightCurrentSelected();
    }

    function handleDrawMouseDown(e) {
        const rect = c.getBoundingClientRect();
        const x = e.clientX - rect.left;
        const y = e.clientY - rect.top;

        // Check if clicking on a resize handle
        if (drawnBox) {
            resizeHandle = getResizeHandle(x, y);
            if (resizeHandle) {
                isDrawing = true;
                drawStartX = x;
                drawStartY = y;
                return;
            }

            // Check if clicking inside the box (for dragging)
            if (isInsideBox(x, y)) {
                isDragging = true;
                dragOffsetX = x - drawnBox.x;
                dragOffsetY = y - drawnBox.y;
                $selectorCanvasElem.css('cursor', 'move');
                return;
            }
        }

        // Start new box
        isDrawing = true;
        drawStartX = x;
        drawStartY = y;
        drawnBox = { x: x, y: y, width: 0, height: 0 };
    }

    function handleDrawMouseMove(e) {
        const rect = c.getBoundingClientRect();
        const x = e.clientX - rect.left;
        const y = e.clientY - rect.top;

        // Update cursor based on position
        if (!isDrawing && !isDragging && drawnBox) {
            const handle = getResizeHandle(x, y);
            if (handle) {
                $selectorCanvasElem.css('cursor', getHandleCursor(handle));
            } else if (isInsideBox(x, y)) {
                $selectorCanvasElem.css('cursor', 'move');
            } else {
                $selectorCanvasElem.css('cursor', 'crosshair');
            }
        }

        // Handle dragging the box
        if (isDragging) {
            drawnBox.x = x - dragOffsetX;
            drawnBox.y = y - dragOffsetY;
            drawBox();
            return;
        }

        if (!isDrawing) return;

        if (resizeHandle) {
            // Resize existing box
            resizeBox(x, y);
        } else {
            // Draw new box
            drawnBox.width = x - drawStartX;
            drawnBox.height = y - drawStartY;
        }

        drawBox();
    }

    function handleDrawMouseUp(e) {
        if (!isDrawing && !isDragging) return;

        isDrawing = false;
        isDragging = false;
        resizeHandle = null;

        if (drawnBox) {
            // Normalize box (handle negative dimensions)
            if (drawnBox.width < 0) {
                drawnBox.x += drawnBox.width;
                drawnBox.width = Math.abs(drawnBox.width);
            }
            if (drawnBox.height < 0) {
                drawnBox.y += drawnBox.height;
                drawnBox.height = Math.abs(drawnBox.height);
            }

            // Constrain to canvas bounds
            drawnBox.x = Math.max(0, Math.min(drawnBox.x, c.width - drawnBox.width));
            drawnBox.y = Math.max(0, Math.min(drawnBox.y, c.height - drawnBox.height));

            // Save to form field (convert from scaled to natural coordinates)
            const naturalX = Math.round(drawnBox.x / xScale);
            const naturalY = Math.round(drawnBox.y / yScale);
            const naturalWidth = Math.round(drawnBox.width / xScale);
            const naturalHeight = Math.round(drawnBox.height / yScale);

            $('#bounding_box').val(`${naturalX},${naturalY},${naturalWidth},${naturalHeight}`);

            drawBox();
        }
    }

    function drawBox() {
        if (!drawnBox) return;

        // Clear and redraw
        ctx.clearRect(0, 0, c.width, c.height);
        xctx.clearRect(0, 0, c.width, c.height);

        // Draw box
        ctx.strokeStyle = STROKE_STYLE_REDLINE;
        ctx.fillStyle = FILL_STYLE_REDLINE;
        ctx.lineWidth = 3;

        const drawX = drawnBox.width >= 0 ? drawnBox.x : drawnBox.x + drawnBox.width;
        const drawY = drawnBox.height >= 0 ? drawnBox.y : drawnBox.y + drawnBox.height;
        const drawW = Math.abs(drawnBox.width);
        const drawH = Math.abs(drawnBox.height);

        ctx.strokeRect(drawX, drawY, drawW, drawH);
        ctx.fillRect(drawX, drawY, drawW, drawH);

        // Draw resize handles
        if (!isDrawing) {
            drawResizeHandles(drawX, drawY, drawW, drawH);
        }
    }

    function drawResizeHandles(x, y, w, h) {
        ctx.fillStyle = '#fff';
        ctx.strokeStyle = '#000';
        ctx.lineWidth = 1;

        const handles = [
            { x: x, y: y },                    // top-left
            { x: x + w, y: y },                // top-right
            { x: x, y: y + h },                // bottom-left
            { x: x + w, y: y + h }             // bottom-right
        ];

        handles.forEach(handle => {
            ctx.fillRect(handle.x - HANDLE_SIZE/2, handle.y - HANDLE_SIZE/2, HANDLE_SIZE, HANDLE_SIZE);
            ctx.strokeRect(handle.x - HANDLE_SIZE/2, handle.y - HANDLE_SIZE/2, HANDLE_SIZE, HANDLE_SIZE);
        });
    }

    function isInsideBox(x, y) {
        if (!drawnBox) return false;

        const drawX = drawnBox.width >= 0 ? drawnBox.x : drawnBox.x + drawnBox.width;
        const drawY = drawnBox.height >= 0 ? drawnBox.y : drawnBox.y + drawnBox.height;
        const drawW = Math.abs(drawnBox.width);
        const drawH = Math.abs(drawnBox.height);

        return x >= drawX && x <= drawX + drawW && y >= drawY && y <= drawY + drawH;
    }

    function getResizeHandle(x, y) {
        if (!drawnBox) return null;

        const drawX = drawnBox.width >= 0 ? drawnBox.x : drawnBox.x + drawnBox.width;
        const drawY = drawnBox.height >= 0 ? drawnBox.y : drawnBox.y + drawnBox.height;
        const drawW = Math.abs(drawnBox.width);
        const drawH = Math.abs(drawnBox.height);

        const handles = {
            'tl': { x: drawX, y: drawY },
            'tr': { x: drawX + drawW, y: drawY },
            'bl': { x: drawX, y: drawY + drawH },
            'br': { x: drawX + drawW, y: drawY + drawH }
        };

        for (const [key, handle] of Object.entries(handles)) {
            if (Math.abs(x - handle.x) <= HANDLE_SIZE && Math.abs(y - handle.y) <= HANDLE_SIZE) {
                return key;
            }
        }

        return null;
    }

    function getHandleCursor(handle) {
        const cursors = {
            'tl': 'nw-resize',
            'tr': 'ne-resize',
            'bl': 'sw-resize',
            'br': 'se-resize'
        };
        return cursors[handle] || 'crosshair';
    }

    function resizeBox(x, y) {
        const dx = x - drawStartX;
        const dy = y - drawStartY;

        const originalBox = { ...drawnBox };

        switch (resizeHandle) {
            case 'tl':
                drawnBox.x = x;
                drawnBox.y = y;
                drawnBox.width = originalBox.x + originalBox.width - x;
                drawnBox.height = originalBox.y + originalBox.height - y;
                break;
            case 'tr':
                drawnBox.y = y;
                drawnBox.width = x - originalBox.x;
                drawnBox.height = originalBox.y + originalBox.height - y;
                break;
            case 'bl':
                drawnBox.x = x;
                drawnBox.width = originalBox.x + originalBox.width - x;
                drawnBox.height = y - originalBox.y;
                break;
            case 'br':
                drawnBox.width = x - originalBox.x;
                drawnBox.height = y - originalBox.y;
                break;
        }

        drawStartX = x;
        drawStartY = y;
    }
});