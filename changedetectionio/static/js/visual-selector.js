// Copyright (C) 2021 Leigh Morresi (dgtlmoon@gmail.com)
// All rights reserved.
// yes - this is really a hack, if you are a front-ender and want to help, please get in touch!

$(document).ready(function () {

    var current_selections= [];
    var current_selection = false;

    var state_clicked = false;

    var c;

    // greyed out fill context
    var xctx;

    // redline highlight context
    var ctx;

    var x_scale = 1;
    var y_scale = 1;
    var selector_image;
    var selector_image_rect;
    var selector_data;
    var append_to_list = false;

    $('#visualselector-tab').click(function () {
        $("img#selector-background").off('load');
        state_clicked = false;
        current_selections = [];
        bootstrap_visualselector();
    });

    function clear_reset() {
        state_clicked = false;
        ctx.clearRect(0, 0, c.width, c.height);
        if ($("#include_filters").val().length) {
            alert("Existing filters under the 'Filters & Triggers' tab were cleared.");
        }
        $("#include_filters").val('');
        current_selections = [];
        highlight_current_selected();
    }

    function splitToList(v) {
        return v.split('\n').map(line => line.trim()).filter(line => line.length > 0);
    }

    $(document).on('keydown', function (event) {
        if ($("img#selector-background").is(":visible")) {
            if (event.key == "Escape") {
                clear_reset();
            }
        }
    });

    $(document).on('keydown keyup', function (event) {
        if (event.code === 'ShiftLeft') {
            append_to_list = event.type === 'keydown';
        } else if (event.code === 'ShiftRight') {
            append_to_list = event.type === 'keydown';
        }
    });

    // Handle clearing button/link
    $('#clear-selector').on('click', function (event) {
        clear_reset();
    });

    // For when the page loads
    if (!window.location.hash || window.location.hash != '#visualselector') {
        $("img#selector-background").attr('src', '');
        return;
    }


    bootstrap_visualselector();


    function bootstrap_visualselector() {
        if (1) {
            // bootstrap it, this will trigger everything else
            $("img#selector-background").on("error", function () {
                $('.fetching-update-notice').html("<strong>Ooops!</strong> The VisualSelector tool needs atleast one fetched page, please unpause the watch and/or wait for the watch to complete fetching and then reload this page.");
                $('.fetching-update-notice').css('color','#bb0000');
                $('#selector-current-xpath').hide();
                $('#clear-selector').hide();
            }).bind('load', function () {
                console.log("Loaded background...");
                c = document.getElementById("selector-canvas");
                // greyed out fill context
                xctx = c.getContext("2d");
                // redline highlight context
                ctx = c.getContext("2d");
                fetch_data();
                $('#selector-canvas').off("mousemove mousedown");
                // screenshot_url defined in the edit.html template
            }).attr("src", screenshot_url);
        }
        // Tell visualSelector that the image should update
        var s = $("img#selector-background").attr('src') + "?" + new Date().getTime();
        $("img#selector-background").attr('src', s)
    }

    // This is fired once the img src is loaded in bootstrap_visualselector()
    function fetch_data() {
        // Image is ready
        $('.fetching-update-notice').html("Fetching element data..");

        $.ajax({
            url: watch_visual_selector_data_url,
            context: document.body
        }).done(function (data) {
            $('.fetching-update-notice').html("Rendering..");
            selector_data = data;
            console.log("Reported browser width from backend: " + data['browser_width']);
            state_clicked = false;
            set_scale();
            reflow_selector();
            $('.fetching-update-notice').fadeOut();
        });

    }


    function set_scale() {

        // some things to check if the scaling doesnt work
        // - that the widths/sizes really are about the actual screen size cat elements.json |grep -o width......|sort|uniq
        $("#selector-wrapper").show();
        selector_image = $("img#selector-background")[0];
        selector_image_rect = selector_image.getBoundingClientRect();

        // Make the overlayed canvas the same size as the image
        $('#selector-canvas').attr('height', selector_image_rect.height).attr('width', selector_image_rect.width);
        $('#selector-wrapper').attr('width', selector_image_rect.width);

        x_scale = selector_image_rect.width / selector_image.naturalWidth;
        y_scale = selector_image_rect.height / selector_image.naturalHeight;

        ctx.strokeStyle = 'rgba(255,0,0, 0.9)';
        ctx.fillStyle = 'rgba(255,0,0, 0.1)';
        ctx.lineWidth = 3;
        console.log("scaling set  x: " + x_scale + " by y:" + y_scale);
        $("#selector-current-xpath").css('max-width', selector_image_rect.width);
    }

    function reflow_selector() {
        $(window).resize(function () {
            set_scale();
            highlight_current_selected();
        });
        
        var selector_currnt_xpath_text = $("#selector-current-xpath span");

        set_scale();

        console.log(selector_data['size_pos'].length + " selectors found");


        existing_filters = splitToList($("#include_filters").val());

        // Different list in the future ? some attrib to tag it as subtract?
        //existing_filters.concat(splitToList($("#subtractive_selectors").val()));

        selector_data['size_pos'].forEach(sel => {
            // @todo || or sel.xpath is in the list split by line etc
            if (sel.highlight_as_custom_filter || existing_filters.includes(sel.xpath)) {
                console.log("highlighting " + c);
                current_selections.push(sel);
            }
        });
        highlight_current_selected();


        $('#selector-canvas').bind('mousemove', function (e) {
            // Keep the current ones

            // Add in offset
            if ((typeof e.offsetX === "undefined" || typeof e.offsetY === "undefined") || (e.offsetX === 0 && e.offsetY === 0)) {
                var targetOffset = $(e.target).offset();
                e.offsetX = e.pageX - targetOffset.left;
                e.offsetY = e.pageY - targetOffset.top;
            }

            // Reverse order - the most specific one should be deeper/"laster", Basically, find the most 'deepest'

            ctx.fillStyle = 'rgba(205,0,0,0.35)';
            // Will be sorted by smallest width*height first
            for (var i = 0; i <= selector_data['size_pos'].length; i++) {
                // draw all of them? let them choose somehow?
                var sel = selector_data['size_pos'][i];
                // If we are in a bounding-box
                if (e.offsetY > sel.top * y_scale && e.offsetY < sel.top * y_scale + sel.height * y_scale
                    &&
                    e.offsetX > sel.left * y_scale && e.offsetX < sel.left * y_scale + sel.width * y_scale

                ) {
                    // FOUND ONE
                    set_current_selected_text(sel.xpath);
                    ctx.strokeRect(sel.left * x_scale, sel.top * y_scale, sel.width * x_scale, sel.height * y_scale);
                    ctx.fillRect(sel.left * x_scale, sel.top * y_scale, sel.width * x_scale, sel.height * y_scale);
                    current_selections.push(sel);
                    current_selection = sel;
                    highlight_current_selected();
                    // Can be removed since we are only using it to preview
                    current_selections.pop();
                    break;
                }
            }

        }.debounce(5));

        function set_current_selected_text(s) {
            selector_currnt_xpath_text[0].innerHTML = s;
        }

        function highlight_current_selected() {
            xctx.fillStyle = 'rgba(205,205,205,0.95)';
            xctx.strokeStyle = 'rgba(225,0,0,0.9)';
            xctx.lineWidth = 3;
            xctx.clearRect(0, 0, c.width, c.height);
            current_selections.forEach(sel => {
                xctx.clearRect(sel.left * x_scale, sel.top * y_scale, sel.width * x_scale, sel.height * y_scale);
                xctx.strokeRect(sel.left * x_scale, sel.top * y_scale, sel.width * x_scale, sel.height * y_scale);
            });

        }

        $('#selector-canvas').bind('mousedown', function (event) {
            current_selections = append_to_list ? [...current_selections, current_selection] : [current_selection];
            highlight_current_selected();
            // Update the filters text
            var textbox_filter_text = "";
            current_selections.forEach(sel => {
                textbox_filter_text += (sel[0] === '/' ? 'xpath:' + sel.xpath : sel.xpath) + "\n";
            });
            $("#include_filters").val(textbox_filter_text);
        });
    }

});