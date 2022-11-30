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
    var browsersteps_session_id;
    var browserless_seconds_remaining=0;
    var apply_buttons_disabled = false;
    var include_text_elements = $("#include_text_elements");
    var xpath_data;
    var current_selected_i;
    var state_clicked = false;
    var c;

    // redline highlight context
    var ctx;
    var last_click_xy = {'x': -1, 'y': -1}

    $(window).resize(function () {
        set_scale();
    });

    $('#browsersteps-click-start').click(function () {
        $("#browsersteps-click-start").fadeOut();
        $("#browsersteps-selector-wrapper .spinner").fadeIn();
        start();
    });

    $('a#browsersteps-tab').click(function () {
       reset();
    });

    window.addEventListener('hashchange', function () {
        if (window.location.hash == '#browser-steps') {
            reset();
        }
    });

    function reset() {
        xpath_data=[];
        $('#browsersteps-img').attr('src', "");
        $("#browsersteps-click-start").show();
        $("#browsersteps-selector-wrapper .spinner").hide();
        browserless_seconds_remaining=0;
    }

    // Show seconds remaining until playwright/browserless needs to restart the session
    // (See comment at the top of changedetectionio/blueprint/browser_steps/__init__.py )
    setInterval(() => {
        if (browserless_seconds_remaining >= 1) {
            document.getElementById('browserless-seconds-remaining').innerText = browserless_seconds_remaining + " seconds remaining in session";
            browserless_seconds_remaining -= 1;
        }
    }, "1000")


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

        document.getElementById("browsersteps-selector-canvas");
        c = document.getElementById("browsersteps-selector-canvas");
        // redline highlight context
        ctx = c.getContext("2d");
        // @todo is click better?
        $('#browsersteps-selector-canvas').off("mousemove mousedown click");
        // Undo disable_browsersteps_ui
        $("#browser_steps select,input").removeAttr('disabled').css('opacity', '1.0');
        $("#browser-steps-ui").css('opacity', '1.0');

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
            console.log("current xpath in index is "+current_selected_i);
            last_click_xy = {'x': parseInt((1 / x_scale) * e.offsetX), 'y': parseInt((1 / y_scale) * e.offsetY)}
            process_selected(current_selected_i);
            current_selected_i = false;

            // if process selected returned false, then best we can do is offer a x,y click :(
            if (!found_something) {
                var first_available = $("ul#browser_steps li.empty").first();
                $('select', first_available).val('Click X,Y').change();
                $('input[type=text]', first_available).first().val(last_click_xy['x'] + ',' + last_click_xy['y']);
                draw_circle_on_canvas(e.offsetX, e.offsetY);
            }
        });

        $('#browsersteps-selector-canvas').bind('mousemove', function (e) {
            // checkbox if find elements is enabled
            ctx.clearRect(0, 0, c.width, c.height);
            ctx.fillStyle = 'rgba(255,0,0, 0.1)';
            ctx.strokeStyle = 'rgba(255,0,0, 0.9)';

            // Add in offset
            if ((typeof e.offsetX === "undefined" || typeof e.offsetY === "undefined") || (e.offsetX === 0 && e.offsetY === 0)) {
                var targetOffset = $(e.target).offset();
                e.offsetX = e.pageX - targetOffset.left;
                e.offsetY = e.pageY - targetOffset.top;
            }
            current_selected_i = false;
            // Reverse order - the most specific one should be deeper/"laster"
            // Basically, find the most 'deepest'
            //$('#browsersteps-selector-canvas').css('cursor', 'pointer');
            for (var i = xpath_data['size_pos'].length; i !== 0; i--) {
                // draw all of them? let them choose somehow?
                var sel = xpath_data['size_pos'][i - 1];
                // If we are in a bounding-box
                if (e.offsetY > sel.top * y_scale && e.offsetY < sel.top * y_scale + sel.height * y_scale
                    &&
                    e.offsetX > sel.left * y_scale && e.offsetX < sel.left * y_scale + sel.width * y_scale

                ) {
                    // Only highlight these interesting types
                    if (1) {
                        ctx.strokeRect(sel.left * x_scale, sel.top * y_scale, sel.width * x_scale, sel.height * y_scale);
                        ctx.fillRect(sel.left * x_scale, sel.top * y_scale, sel.width * x_scale, sel.height * y_scale);
                        current_selected_i = i - 1;
                        break;

                        // find the smallest one at this x,y
                        // does it mean sort the xpath list by size (w*h) i think so!
                    } else {

                        if ( include_text_elements[0].checked === true) {
                        // blue one with background instead?
                            ctx.fillStyle = 'rgba(0,0,255, 0.1)';
                            ctx.strokeStyle = 'rgba(0,0,200, 0.7)';
                            $('#browsersteps-selector-canvas').css('cursor', 'grab');
                            ctx.strokeRect(sel.left * x_scale, sel.top * y_scale, sel.width * x_scale, sel.height * y_scale);
                            ctx.fillRect(sel.left * x_scale, sel.top * y_scale, sel.width * x_scale, sel.height * y_scale);
                            current_selected_i = i - 1;
                            break;
                        }
                    }
                }
            }

        }.debounce(10));
    });

//    $("#browser-steps-fieldlist").bind('mouseover', function(e) {
//        console.log(e.xpath_data_index);
    // });



    // callback for clicking on an xpath on the canvas
    function process_selected(xpath_data_index) {
        found_something = false;
        var first_available = $("ul#browser_steps li.empty").first();


        if (xpath_data_index !== false) {
            // Nothing focused, so fill in a new one
            // if inpt type button or <button>
            // from the top, find the next not used one and use it
            var x = xpath_data['size_pos'][xpath_data_index];
            console.log(x);
            if (x && first_available.length) {
                // @todo will it let you click shit that has a layer ontop? probably not.
                if (x['tagtype'] === 'text' || x['tagtype'] === 'email' || x['tagName'] === 'textarea' || x['tagtype'] === 'password' || x['tagtype'] === 'search' ) {
                    $('select', first_available).val('Enter text in field').change();
                    $('input[type=text]', first_available).first().val(x['xpath']);
                    $('input[placeholder="Value"]', first_available).addClass('ok').click().focus();
                    found_something = true;
                } else {
                    if (x['isClickable'] || x['tagName'].startsWith('h')|| x['tagName'] === 'a' || x['tagName'] === 'button' || x['tagtype'] === 'submit'|| x['tagtype'] === 'checkbox'|| x['tagtype'] === 'radio'|| x['tagtype'] === 'li') {
                        $('select', first_available).val('Click element').change();
                        $('input[type=text]', first_available).first().val(x['xpath']);
                        found_something = true;
                    }
                }

                first_available.xpath_data_index=xpath_data_index;

                if (!found_something) {
                    if ( include_text_elements[0].checked === true) {
                        // Suggest that we use as filter?
                        // @todo filters should always be in the last steps, nothing non-filter after it
                        found_something = true;
                        ctx.strokeStyle = 'rgba(0,0,255, 0.9)';
                        ctx.fillStyle = 'rgba(0,0,255, 0.1)';
                        $('select', first_available).val('Extract text and use as filter').change();
                        $('input[type=text]', first_available).first().val(x['xpath']);
                        include_text_elements[0].checked = false;
                    }
                }
            }
        }
    }

    function draw_circle_on_canvas(x, y) {
        ctx.beginPath();
        ctx.arc(x, y, 8, 0, 2 * Math.PI, false);
        ctx.fillStyle = 'rgba(255,0,0, 0.6)';
        ctx.fill();
    }

    function start() {
        console.log("Starting browser-steps UI");
        browsersteps_session_id=Date.now();
        // @todo This setting of the first one should be done at the datalayer but wtforms doesnt wanna play nice
        $('#browser_steps >li:first-child').removeClass('empty');
        $('#browser_steps >li:first-child select').val('Goto site').attr('disabled', 'disabled');
        $('#browser-steps-ui .loader .spinner').show();
        $('.clear,.remove', $('#browser_steps >li:first-child')).hide();
        $.ajax({
            type: "GET",
            url: browser_steps_sync_url+"&browsersteps_session_id="+browsersteps_session_id,
            statusCode: {
                400: function () {
                    // More than likely the CSRF token was lost when the server restarted
                    alert("There was a problem processing the request, please reload the page.");
                }
            }
        }).done(function (data) {
            xpath_data = data.xpath_data;
            $('#browsersteps-img').attr('src', data.screenshot);
            $("#loading-status-text").fadeIn();
            // This should trigger 'Goto site'
            $('#browser_steps >li:first-child .apply').click();
            browserless_seconds_remaining = data.browser_time_remaining;
        }).fail(function (data) {
            console.log(data);
            alert('There was an error communicating with the server.');
        });

    }

    function disable_browsersteps_ui() {
        $("#browser_steps select,input").attr('disabled', 'disabled').css('opacity', '0.5');
        $("#browser-steps-ui").css('opacity', '0.3');
        $('#browsersteps-selector-canvas').off("mousemove mousedown click");
    }


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

    function set_greyed_state() {
        $('ul#browser_steps select').not('option:selected[value="Choose one"]').closest('li').removeClass('empty');
        $('ul#browser_steps select option:selected[value="Choose one"]').closest('li').addClass('empty');
    }

    // Add the extra buttons to the steps
    $('ul#browser_steps li').each(function (i) {
            $(this).append('<div class="control">' +
                '<a data-step-index=' + i + ' class="pure-button button-secondary button-green button-xsmall apply" >Apply</a>&nbsp;' +
                '<a data-step-index=' + i + ' class="pure-button button-secondary button-xsmall clear" >Clear</a>&nbsp;' +
                '<a data-step-index=' + i + ' class="pure-button button-secondary button-red button-xsmall remove" >Remove</a>' +
                '</div>')
        }
    );

    $('ul#browser_steps li .control .clear').click(function (element) {
        $("select", $(this).closest('li')).val("Choose one").change();
        $(":text", $(this).closest('li')).val('');
    });


    $('ul#browser_steps li .control .remove').click(function (element) {
        // so you wanna remove the 2nd (3rd spot 0,1,2,...)
        var p = $("#browser_steps li").index($(this).closest('li'));

        var elem_to_remove = $("#browser_steps li")[p];
        $('.clear', elem_to_remove).click();
        $("#browser_steps li").slice(p, 10).each(function (index) {
            // get the next one's value from where we clicked
            var next = $("#browser_steps li")[p + index + 1];
            if (next) {
                // and set THIS ones value from the next one
                var n = $('input', next);
                $("select", $(this)).val($('select', next).val());
                $('input', this)[0].value = $(n)[0].value;
                $('input', this)[1].value = $(n)[1].value;
                // Triggers reconfiguring the field based on the system config
                $("select", $(this)).change();
            }

        });

        // Reset their hidden/empty states
        set_greyed_state();
    });

    $('ul#browser_steps li .control .apply').click(function (event) {
        // sequential requests @todo refactor
        if(apply_buttons_disabled) {
            return;
        }

        var current_data = $(event.currentTarget).closest('li');
        $('#browser-steps-ui .loader .spinner').fadeIn();
        apply_buttons_disabled=true;
        $('ul#browser_steps li .control .apply').css('opacity',0.5);
        $("#browsersteps-img").css('opacity',0.65);

        var is_last_step = 0;
        var step_n = $(event.currentTarget).data('step-index');

        // On the last step, we should also be getting data ready for the visual selector
        $('ul#browser_steps li select').each(function (i) {
            if ($(this).val() !== 'Choose one') {
                is_last_step += 1;
            }
        });

        if (is_last_step == (step_n+1)) {
            is_last_step = true;
        } else {
            is_last_step = false;
        }


        // POST the currently clicked step form widget back and await response, redraw
        $.ajax({
            method: "POST",
            url: browser_steps_sync_url+"&browsersteps_session_id="+browsersteps_session_id,
            data: {
                'operation': $("select[id$='operation']", current_data).first().val(),
                'selector': $("input[id$='selector']", current_data).first().val(),
                'optional_value': $("input[id$='optional_value']", current_data).first().val(),
                'step_n': step_n,
                'is_last_step': is_last_step
            },
            statusCode: {
                400: function () {
                    // More than likely the CSRF token was lost when the server restarted
                    alert("There was a problem processing the request, please reload the page.");
                    $("#loading-status-text").hide();
                }
            }
        }).done(function (data) {
            // it should return the new state (selectors available and screenshot)
            xpath_data = data.xpath_data;
            $('#browsersteps-img').attr('src', data.screenshot);
            $('#browser-steps-ui .loader .spinner').fadeOut();
            apply_buttons_disabled=false;
            $("#browsersteps-img").css('opacity',1);
            $('ul#browser_steps li .control .apply').css('opacity',1);
            browserless_seconds_remaining = data.browser_time_remaining;
            $("#loading-status-text").hide();
        }).fail(function (data) {
            console.log(data);
            if (data.responseText.includes("Browser session expired")) {
                disable_browsersteps_ui();
            }
            apply_buttons_disabled=false;
            $("#loading-status-text").hide();
            $('ul#browser_steps li .control .apply').css('opacity',1);
            $("#browsersteps-img").css('opacity',1);
            //$('#browsersteps-selector-wrapper .loader').fadeOut(2500);
        });

    });


    $("ul#browser_steps select").change(function () {
        set_greyed_state();
    }).change();

});