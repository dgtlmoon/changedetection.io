$(document).ready(function () {

    var xpath_data;
    var current_selected_i;
    var state_clicked = false;
    var c;
    // greyed out fill context
    var xctx;
    // redline highlight context
    var ctx;

    var current_focused_step_form_input = false;

    function set_scale() {

        // some things to check if the scaling doesnt work
        // - that the widths/sizes really are about the actual screen size cat elements.json |grep -o width......|sort|uniq
        selector_image = $("img#browsersteps-img")[0];
        selector_image_rect = selector_image.getBoundingClientRect();

        // make the canvas the same size as the image
        $('#browsersteps-selector-canvas').attr('height', selector_image_rect.height).attr('width', selector_image_rect.width);
        $('#browsersteps-selector-wrapper').attr('width', selector_image_rect.width);
        x_scale = selector_image_rect.width / xpath_data['browser_width'];
        y_scale = selector_image_rect.height / selector_image.naturalHeight;
        ctx.strokeStyle = 'rgba(255,0,0, 0.9)';
        ctx.fillStyle = 'rgba(255,0,0, 0.1)';
        ctx.lineWidth = 3;
        console.log("scaling set  x: " + x_scale + " by y:" + y_scale);
        $("#browsersteps-selector-current-xpath").css('max-width', selector_image_rect.width);
    }

    // bootstrap it, this will trigger everything else
    $('#browsersteps-img').bind('load', function () {
        console.log("Loaded background...");

        document.getElementById("browsersteps-selector-canvas");
        c = document.getElementById("browsersteps-selector-canvas");
        // greyed out fill context
        xctx = c.getContext("2d");
        // redline highlight context
        ctx = c.getContext("2d");
        $('#browsersteps-selector-canvas').off("mousemove mousedown");

        // init
        set_scale();
        $('#browsersteps-selector-canvas').bind('mousedown', function (e) {
            process_selected(current_selected_i);
            current_selected_i=false;
        });

        $('#browsersteps-selector-canvas').bind('mousemove', function (e) {
            ctx.clearRect(0, 0, c.width, c.height);

            // Add in offset
            if ((typeof e.offsetX === "undefined" || typeof e.offsetY === "undefined") || (e.offsetX === 0 && e.offsetY === 0)) {
                var targetOffset = $(e.target).offset();
                e.offsetX = e.pageX - targetOffset.left;
                e.offsetY = e.pageY - targetOffset.top;
            }

            // Reverse order - the most specific one should be deeper/"laster"
            // Basically, find the most 'deepest'
            ctx.fillStyle = 'rgba(205,0,0,0.35)';
            for (var i = xpath_data['size_pos'].length; i !== 0; i--) {
                // draw all of them? let them choose somehow?
                var sel = xpath_data['size_pos'][i - 1];
                // If we are in a bounding-box
                if (e.offsetY > sel.top * y_scale && e.offsetY < sel.top * y_scale + sel.height * y_scale
                    &&
                    e.offsetX > sel.left * y_scale && e.offsetX < sel.left * y_scale + sel.width * y_scale

                ) {
                    ctx.strokeRect(sel.left * x_scale, sel.top * y_scale, sel.width * x_scale, sel.height * y_scale);
                    ctx.fillRect(sel.left * x_scale, sel.top * y_scale, sel.width * x_scale, sel.height * y_scale);
                    current_selected_i = i - 1;
                    break;
                }
            }

        }.debounce(5));
    });

    // callback for clicking on an xpath on the canvas
    function process_selected(xpath_data_index) {
        console.log(xpath_data['size_pos'][xpath_data_index]);

        // Fill in the current focused input
        if (current_focused_step_form_input) {
            $(current_focused_step_form_input).val(xpath_data['size_pos'][xpath_data_index]['xpath']);
        } else {
            if (xpath_data_index !== false) {
                // Nothing focused, so fill in a new one
                // if inpt type button or <button>
                // from the top, find the next not used one and use it
                var first_available = $("ul#browser_steps li.empty").first();
                var x = xpath_data['size_pos'][xpath_data_index];
                if (first_available.length) {
                    if (x['tagtype'] === 'text' || x['tagtype'] === 'password') {
                        $('input[type=text]', first_available).first().val(x['xpath']);
                        $('select', first_available).val('Enter text in field').change();
                    }
                    if (x['tagtype'] === 'button' || x['tagtype'] === 'submit') {
                        $('input[type=text]', first_available).first().val(x['xpath']);
                        $('select', first_available).val('Click button').change();
                    }
                }
            }
        }

    }


    $.ajax({
        type: "GET",
        url: browser_steps_sync_url,
        statusCode: {
            400: function () {
                // More than likely the CSRF token was lost when the server restarted
                alert("There was a problem processing the request, please reload the page.");
            }
        }
    }).done(function (data) {
        xpath_data = data.xpath_data;
        $('#browsersteps-img').attr('src', data.screenshot);
    }).fail(function (data) {
        console.log(data);
        alert('There was an error communicating with the server.');
    });


    ////////////////////////// STEPS UI ////////////////////

    // Look up which step was selected, and enable or disable the related extra fields
    // So that people using it dont' get confused
    $('ul#browser_steps select').on("change", function () {
        var config = browser_steps_config[$(this).val()].split(' ');
        var elem_selector = $('tr:nth-child(2) input', $(this).closest('tbody'));
        var elem_value = $('tr:nth-child(3) input', $(this).closest('tbody'));

        if (config[0] == 0) {
            $(elem_selector).fadeOut();
        } else {
            $(elem_selector).fadeIn();
        }
        if (config[1] == 0) {
            $(elem_value).fadeOut();
        } else {
            $(elem_value).fadeIn();
        }
    });
    $('ul#browser_steps select').change();

    $('#browser-steps input[type=text]').first().on("focus", function () {
        current_focused_step_form_input = this;
    });

    function set_greyed_state() {
        $('ul#browser_steps select ').not('option:selected[value="Choose one"]').closest('li').css('opacity', 1).removeClass('empty');
        $('ul#browser_steps select option:selected[value="Choose one"]').closest('li').css('opacity', 0.35).addClass('empty');
    }

    $("ul#browser_steps select").change(function () {
        set_greyed_state();
    });
    set_greyed_state();
});