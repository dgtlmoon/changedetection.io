$(document).ready(function() {


    var current_selected_i;
    var state_clicked=false;

    var c = document.getElementById("selector-canvas");

    // greyed out fill context
    var xctx = c.getContext("2d");
    // redline highlight context
    var ctx = c.getContext("2d");

    var current_default_xpath=$("#css_filter").val();
    var x_scale=1;
    var y_scale=1;
    var selector_image = document.getElementById("selector-background");
    var selector_image_rect;
    var vh;
    var selector_data;


    if ( $("img#selector-background").is(':visible') ) {
        // bootstrap it, this will trigger everything else
        $("img#selector-background").bind('load', function () {
           fetch_data();
        }).attr("src", screenshot_url);
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
        set_scale();
        reflow_selector();
        $('.fetching-update-notice').fadeOut();
      });
    };

    $(document).on('keydown', function(event) {
      if (event.key == "Escape") {
        state_clicked=false;
      }
    });

    $(window).resize(function() {
        set_scale();
    });

    function set_scale() {

      // some things to check if the scaling doesnt work
      // - that the widths/sizes really are about the actual screen size cat elements.json |grep -o width......|sort|uniq

      selector_image_rect = selector_image.getBoundingClientRect();


      // make the canvas the same size as the image
      $('#selector-canvas').attr('height', selector_image_rect.height);
      $('#selector-canvas').attr('width', selector_image_rect.width);
      $('#selector-wrapper').attr('width', selector_image_rect.width);
      x_scale = selector_image_rect.width / selector_data['browser_width'];
      y_scale = selector_image_rect.height / selector_image.naturalHeight;
       console.log(selector_image_rect.width +" "+ selector_image.naturalWidth);
      ctx.strokeStyle = 'rgba(255,0,0, 0.8)';
      ctx.fillStyle = 'rgba(255,0,0, 0.1)';
      ctx.lineWidth = 3;
      console.log("scaling set  x: "+x_scale+" by y:"+y_scale);
    }

    function reflow_selector() {

      var selector_currnt_xpath_text=$("#selector-current-xpath span");

      set_scale();

      console.log(selector_data['size_pos'].length + " selectors found");

      // highlight the default one if we can find it in the xPath list
      // or the xpath matches the default one
      for (var i = selector_data['size_pos'].length; i!==0; i--) {
        var sel = selector_data['size_pos'][i-1];
        if(selector_data['size_pos'][i - 1].xpath == current_default_xpath) {
          ctx.strokeRect(sel.left * x_scale, sel.top * y_scale, sel.width * x_scale, sel.height * y_scale);
          current_selected_i=i-1;
          highlight_current_selected_i();
          break;
        }
      }


      $('#selector-canvas').bind('mousemove', function (e) {

        if(state_clicked) {
          return;
        }
        ctx.clearRect(0, 0, c.width, c.height);
        current_selected_i=null;

        // Reverse order - the most specific one should be deeper/"laster"
        // Basically, find the most 'deepest'
        var found=0;
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
        console.log("Found elements depth "+found);
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
        $("#css_filter").val('xpath:'+sel.xpath);
        xctx.fillStyle = 'rgba(225,225,225,0.8)';
        xctx.fillRect(0,0,c.width, c.height);
        xctx.clearRect(sel.left * x_scale, sel.top * y_scale, sel.width * x_scale, sel.height * y_scale);
        state_clicked=true;
        set_current_selected_text(sel.xpath);

      }


      $('#selector-canvas').bind('mousedown', function (e) {
        highlight_current_selected_i();
      });
    }

});
