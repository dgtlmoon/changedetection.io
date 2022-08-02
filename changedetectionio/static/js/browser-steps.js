$(document).ready(function () {

    // duplicate
    var csrftoken = $('input[name=csrf_token]').val();
    $.ajaxSetup({
        beforeSend: function (xhr, settings) {
            if (!/^(GET|HEAD|OPTIONS|TRACE)$/i.test(settings.type) && !this.crossDomain) {
                xhr.setRequestHeader("X-CSRFToken", csrftoken)
            }
        }
    })


    var xpath_data;
    var current_selected_i;
    var state_clicked = false;
    var c;

    // redline highlight context
    var ctx;
    var last_click_xy = {'x': -1, 'y': -1}

    var current_focused_step_form_input = false;

    function set_scale() {

        // some things to check if the scaling doesnt work
        // - that the widths/sizes really are about the actual screen size cat elements.json |grep -o width......|sort|uniq
        selector_image = $("img#browsersteps-img")[0];
        selector_image_rect = selector_image.getBoundingClientRect();

        // make the canvas and input steps the same size as the image
        $('#browsersteps-selector-canvas').attr('height', selector_image_rect.height).attr('width', selector_image_rect.width);
        //$('#browsersteps-selector-wrapper').attr('width', selector_image_rect.width);
        $('#browser-steps-ui').attr('width', selector_image_rect.width);
        x_scale = selector_image_rect.width / xpath_data['browser_width'];
        y_scale = selector_image_rect.height / selector_image.naturalHeight;
        ctx.strokeStyle = 'rgba(255,0,0, 0.9)';
        ctx.fillStyle = 'rgba(255,0,0, 0.1)';
        ctx.lineWidth = 3;
        console.log("scaling set  x: " + x_scale + " by y:" + y_scale);
    }

    // bootstrap it, this will trigger everything else
    $('#browsersteps-img').bind('load', function () {
        $('body').addClass('full-width');
        console.log("Loaded background...");
        $('#browsersteps-selector-wrapper .loader').fadeOut(2500);

        document.getElementById("browsersteps-selector-canvas");
        c = document.getElementById("browsersteps-selector-canvas");
        // redline highlight context
        ctx = c.getContext("2d");
        // @todo is click better?
        $('#browsersteps-selector-canvas').off("mousemove mousedown click");

        // init
        set_scale();

        // @todo click ? some better library?
        $('#browsersteps-selector-canvas').bind('click', function (e) {
            // https://developer.mozilla.org/en-US/docs/Web/API/MouseEvent
            e.preventDefault()
        });

        $('#browsersteps-selector-canvas').bind('mousedown', function (e) {
            // https://developer.mozilla.org/en-US/docs/Web/API/MouseEvent
            e.preventDefault()
            console.log(e);
            last_click_xy = {'x': e.offsetX, 'y': e.offsetY}
            process_selected(current_selected_i);
            current_selected_i = false;

        });

        $('#browsersteps-selector-canvas').bind('mousemove', function (e) {
            // checkbox if find elements is enabled
            ctx.clearRect(0, 0, c.width, c.height);
            ctx.fillStyle = 'rgba(255,0,0, 0.1)';

            // Add in offset
            if ((typeof e.offsetX === "undefined" || typeof e.offsetY === "undefined") || (e.offsetX === 0 && e.offsetY === 0)) {
                var targetOffset = $(e.target).offset();
                e.offsetX = e.pageX - targetOffset.left;
                e.offsetY = e.pageY - targetOffset.top;
            }
            current_selected_i = false;
            // Reverse order - the most specific one should be deeper/"laster"
            // Basically, find the most 'deepest'
            for (var i = xpath_data['size_pos'].length; i !== 0; i--) {
                // draw all of them? let them choose somehow?
                var sel = xpath_data['size_pos'][i - 1];
                // If we are in a bounding-box
                if (e.offsetY > sel.top * y_scale && e.offsetY < sel.top * y_scale + sel.height * y_scale
                    &&
                    e.offsetX > sel.left * y_scale && e.offsetX < sel.left * y_scale + sel.width * y_scale

                ) {
                    // Only highlight these interesting types
                    if (sel['tagtype'] === 'text' ||
                        sel['tagtype'] === 'password' ||
                        sel['tagName'] === 'a' ||
                        sel['tagName'] === 'button' ||
                        sel['tagName'] === 'input') {
                        ctx.strokeRect(sel.left * x_scale, sel.top * y_scale, sel.width * x_scale, sel.height * y_scale);
                        ctx.fillRect(sel.left * x_scale, sel.top * y_scale, sel.width * x_scale, sel.height * y_scale);
                        current_selected_i = i - 1;
                        break;

                    }
                }
            }

        }.debounce(10));
    });

    // callback for clicking on an xpath on the canvas
    function process_selected(xpath_data_index) {
        console.log(xpath_data['size_pos'][xpath_data_index]);
        found_something = false;
        var first_available = $("ul#browser_steps li.empty").first();

        // Fill in the current focused input
        if (current_focused_step_form_input) {
            $(current_focused_step_form_input).val(xpath_data['size_pos'][xpath_data_index]['xpath']);
        } else {
            if (xpath_data_index !== false) {
                // Nothing focused, so fill in a new one
                // if inpt type button or <button>
                // from the top, find the next not used one and use it
                var x = xpath_data['size_pos'][xpath_data_index];
                if (x && first_available.length) {
                    // @todo will it let you click shit that has a layer ontop? probably not.
                    if (x['tagtype'] === 'text' || x['tagtype'] === 'email' || x['tagtype'] === 'password') {
                        $('select', first_available).val('Enter text in field').change();
                        $('input[type=text]', first_available).first().val(x['xpath']);
                        $('input[placeholder="Value"]', first_available).addClass('ok').click().focus();
                        found_something = true;
                    } else {
                        // Assume it's just for clicking on
                        // what are we clicking on?
                        if (x['tagName'] === 'a' || x['tagName'] === 'button' || x['tagtype'] === 'submit') {
                            $('select', first_available).val('Click button').change();
                            $('input[type=text]', first_available).first().val(x['xpath']);
                            found_something = true;
                        }
                    }
                }
            }
        }

        if (xpath_data_index === false && !found_something) {
            $('select', first_available).val('Click X,Y').change();
            $('input[type=text]', first_available).first().val(last_click_xy['x'] + ',' + last_click_xy['y']);
            draw_circle_on_canvas(last_click_xy['x'], last_click_xy['y']);
        }
    }

    function draw_circle_on_canvas(x, y) {
        ctx.beginPath();
        ctx.arc(x, y, 8, 0, 2 * Math.PI, false);
        ctx.fillStyle = 'rgba(255,0,0, 0.6)';
        ctx.fill();
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
    $('ul#browser_steps [type="text"]').keydown(function (e) {
        if (e.keyCode === 13) {
            // hitting [enter] in a browser-step input should trigger the 'Apply'
            e.preventDefault();
            $(".apply", $(this).closest('li')).click();
            return false;
        }
    });

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

        if ($(this).val() === 'Click X,Y' && last_click_xy['x'] > 0 && $(elem_value).val().length === 0) {
            // @todo handle scale
            $(elem_value).val(last_click_xy['x'] + ',' + last_click_xy['y']);
        }
    }).change();

    $('#browser-steps input[type=text]').first().on("focus", function () {
        current_focused_step_form_input = this;
    });

    function set_greyed_state() {
        $('ul#browser_steps select').not('option:selected[value="Choose one"]').closest('li').css('opacity', 1).removeClass('empty');
        $('ul#browser_steps select option:selected[value="Choose one"]').closest('li').css('opacity', 0.35).addClass('empty');
    }

    // Add the extra buttons to the steps
    $('ul#browser_steps li').each(function (i) {
            $(this).append('<div class="control">' +
                '<a data-step-index=' + i + ' class="pure-button button-green button-xsmall apply" >Apply</a>&nbsp;' +
                '<a data-step-index=' + i + ' class="pure-button button-secondary button-xsmall clear" >Clear</a>' +
                '</div>')
        }
    );

    $('ul#browser_steps li .control .clear').click(function (element) {
        $("select", $(this).closest('li')).val("Choose one").change();
        $(":text", $(this).closest('li')).val('');
    });


    $('ul#browser_steps li .control .apply').click(function (element) {
        var current_data = $(element.currentTarget).closest('li');
        $('#browser-steps-ui .loader').fadeIn();
        // POST the currently clicked step form widget back and await response, redraw
        $.ajax({
            method: "POST",
            url: browser_steps_sync_url,
            data: {
                'operation': $("select[id$='operation']", current_data).first().val(),
                'selector': $("input[id$='selector']", current_data).first().val(),
                'optional_value': $("input[id$='optional_value']", current_data).first().val()
            },
            statusCode: {
                400: function () {
                    // More than likely the CSRF token was lost when the server restarted
                    alert("There was a problem processing the request, please reload the page.");
                }
            }
        }).done(function (data) {
            // it should return the new state (selectors available and screenshot)
            xpath_data = data.xpath_data;
            $('#browsersteps-img').attr('src', data.screenshot);
            $('#browser-steps-ui .loader').fadeOut();
        }).fail(function (data) {
            console.log(data);
            alert('There was an error communicating with the server.');
        });

    });


    $("ul#browser_steps select").change(function () {
        set_greyed_state();
    }).change();

});