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

        $selectorCanvasElem.bind('mousemove', handleMouseMove.debounce(5));
        $selectorCanvasElem.bind('mousedown', handleMouseDown.debounce(5));
        $selectorCanvasElem.bind('mouseleave', highlightCurrentSelected.debounce(5));

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
});