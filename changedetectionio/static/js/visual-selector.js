// Horrible proof of concept code :)
// yes - this is really a hack, if you are a front-ender and want to help, please get in touch!

$(document).ready(function() {

    var current_selected_i;
    var state_clicked=false;

    var c;

    // greyed out fill context
    var xctx;
    // redline highlight context
    var ctx;

    var current_default_xpath;
    var x_scale=1;
    var y_scale=1;
    var selector_image;
    var selector_image_rect;
    var selector_data;

    $('#visualselector-tab').click(function () {
        $("img#selector-background").off('load');
        state_clicked = false;
        current_selected_i = false;
        bootstrap_visualselector();
    });

    $(document).on('keydown', function(event) {
        if ($("img#selector-background").is(":visible")) {
            if (event.key == "Escape") {
                state_clicked=false;
                ctx.clearRect(0, 0, c.width, c.height);
            }
        }
    });

    // For when the page loads
    if(!window.location.hash || window.location.hash != '#visualselector') {
        $("img#selector-background").attr('src','');
        return;
    }

    // Handle clearing button/link
    $('#clear-selector').on('click', function(event) {
        if(!state_clicked) {
            alert('Oops, Nothing selected!');
        }
        state_clicked=false;
        ctx.clearRect(0, 0, c.width, c.height);
        xctx.clearRect(0, 0, c.width, c.height);
        $("#css_filter").val('');
    });


    bootstrap_visualselector();



    function bootstrap_visualselector() {
        if ( 1 ) {
            // bootstrap it, this will trigger everything else
            $("img#selector-background").bind('load', function () {
                console.log("Loaded background...");
               c = document.getElementById("selector-canvas");
                // greyed out fill context
               xctx = c.getContext("2d");
                // redline highlight context
               ctx = c.getContext("2d");
               current_default_xpath =$("#css_filter").val();
               fetch_data();
               $('#selector-canvas').off("mousemove mousedown");
               // screenshot_url defined in the edit.html template
            }).attr("src", screenshot_url);
        }
    }

    function fetch_data() {
      // Image is ready
      $('.fetching-update-notice').html("Fetching element data..");

      $.ajax({
        url: watch_visual_selector_data_url,
        context: document.body
      }).done(function (data) {
        $('.fetching-update-notice').html("Rendering..");
        selector_data = data;
        console.log("Reported browser width from backend: "+data['browser_width']);
        state_clicked=false;
        set_scale();
        reflow_selector();
        $('.fetching-update-notice').fadeOut();
      });
    };



    function set_scale() {

      // some things to check if the scaling doesnt work
      // - that the widths/sizes really are about the actual screen size cat elements.json |grep -o width......|sort|uniq
      selector_image = $("img#selector-background")[0];
      selector_image_rect = selector_image.getBoundingClientRect();

      // make the canvas the same size as the image
      $('#selector-canvas').attr('height', selector_image_rect.height);
      $('#selector-canvas').attr('width', selector_image_rect.width);
      $('#selector-wrapper').attr('width', selector_image_rect.width);
      x_scale = selector_image_rect.width / selector_data['browser_width'];
      y_scale = selector_image_rect.height / selector_image.naturalHeight;
      ctx.strokeStyle = 'rgba(255,0,0, 0.9)';
      ctx.fillStyle = 'rgba(255,0,0, 0.1)';
      ctx.lineWidth = 3;
      console.log("scaling set  x: "+x_scale+" by y:"+y_scale);
      $("#selector-current-xpath").css('max-width', selector_image_rect.width);
    }

    function reflow_selector() {
        $(window).resize(function() {
            set_scale();
            highlight_current_selected_i();
        });
      var selector_currnt_xpath_text=$("#selector-current-xpath span");

      set_scale();

      console.log(selector_data['size_pos'].length + " selectors found");

      // highlight the default one if we can find it in the xPath list
      // or the xpath matches the default one
      found = false;
      if(current_default_xpath.length) {
          for (var i = selector_data['size_pos'].length; i!==0; i--) {
            var sel = selector_data['size_pos'][i-1];
            if(selector_data['size_pos'][i - 1].xpath == current_default_xpath) {
            console.log("highlighting "+current_default_xpath);
              current_selected_i = i-1;
              highlight_current_selected_i();
              found = true;
              break;
            }
          }
        if(!found) {
          alert("Unfortunately your existing CSS/xPath Filter was no longer found!");
        }
      }


      $('#selector-canvas').bind('mousemove', function (e) {
        if(state_clicked) {
          return;
        }
        ctx.clearRect(0, 0, c.width, c.height);
        current_selected_i=null;

        // Add in offset
        if ((typeof e.offsetX === "undefined" || typeof e.offsetY === "undefined") || (e.offsetX === 0 && e.offsetY === 0)) {
          var targetOffset = $(e.target).offset();
          e.offsetX = e.pageX - targetOffset.left;
          e.offsetY = e.pageY - targetOffset.top;
        }

        // Reverse order - the most specific one should be deeper/"laster"
        // Basically, find the most 'deepest'
        var found=0;
        ctx.fillStyle = 'rgba(205,0,0,0.35)';
        for (var i = selector_data['size_pos'].length; i!==0; i--) {
          // draw all of them? let them choose somehow?
          var sel = selector_data['size_pos'][i-1];
          // If we are in a bounding-box
          if (e.offsetY > sel.top * y_scale && e.offsetY < sel.top * y_scale + sel.height * y_scale
              &&
              e.offsetX > sel.left * y_scale && e.offsetX < sel.left * y_scale + sel.width * y_scale

          ) {

            // FOUND ONE
            set_current_selected_text(sel.xpath);
            ctx.strokeRect(sel.left * x_scale, sel.top * y_scale, sel.width * x_scale, sel.height * y_scale);
            ctx.fillRect(sel.left * x_scale, sel.top * y_scale, sel.width * x_scale, sel.height * y_scale);

            // no need to keep digging
            // @todo or, O to go out/up, I to go in
            // or double click to go up/out the selector?
            current_selected_i=i-1;
            found+=1;
            break;
          }
        }

      }.debounce(5));

      function set_current_selected_text(s) {
        selector_currnt_xpath_text[0].innerHTML=s;
      }

      function highlight_current_selected_i() {
        if(state_clicked) {
          state_clicked=false;
          xctx.clearRect(0,0,c.width, c.height);
          return;
        }

        var sel = selector_data['size_pos'][current_selected_i];
        if (sel[0] == '/') {
        // @todo - not sure just checking / is right
            $("#css_filter").val('xpath:'+sel.xpath);
        } else {
            $("#css_filter").val(sel.xpath);
        }
        xctx.fillStyle = 'rgba(205,205,205,0.95)';
        xctx.strokeStyle = 'rgba(225,0,0,0.9)';
        xctx.lineWidth = 3;
        xctx.fillRect(0,0,c.width, c.height);
        // Clear out what only should be seen (make a clear/clean spot)
        xctx.clearRect(sel.left * x_scale, sel.top * y_scale, sel.width * x_scale, sel.height * y_scale);
        xctx.strokeRect(sel.left * x_scale, sel.top * y_scale, sel.width * x_scale, sel.height * y_scale);
        state_clicked=true;
        set_current_selected_text(sel.xpath);

      }


      $('#selector-canvas').bind('mousedown', function (e) {
        highlight_current_selected_i();
      });
    }

});
