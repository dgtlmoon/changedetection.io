var current_selected_i;

function fetch_data() {
  // Image is ready
  $('.fetching-update-notice').html("Fetching element data..");

  $.ajax({
    url: watch_visual_selector_data_url,
    context: document.body
  }).done(function (data) {
    $('.fetching-update-notice').html("Rendering..");
    reflow_selector(data);
  });
};


function reflow_selector(selector_data) {

  //  $('#selector-canvas').attr('width',
  // $("img#selector-background")[0].getBoundingClientRect().width);
  var c = document.getElementById("selector-canvas");
  var selector_image = document.getElementById("selector-background");
  var selector_image_rect = selector_image.getBoundingClientRect();

  $('#selector-canvas').attr('height', selector_image_rect.height);
  $('#selector-canvas').attr('width', selector_image_rect.width);


  var ctx = c.getContext("2d");
  ctx.strokeStyle = 'rgba(255,0,0,5)';

  // set this on resize too
  var x_scale = selector_image_rect.width / selector_image.naturalWidth;
  var y_scale = selector_image_rect.height / selector_image.naturalHeight;

  console.log(selector_data.length + " selectors found");
  $('#selector-canvas').bind('mousemove', function (e) {
    ctx.clearRect(0, 0, c.width, c.height);
    current_selected_i=null;

    // Reverse order - the most specific one should be deeper/"laster"
    for (var i = selector_data.length; i!=0; i--) {
      // draw all of them? let them choose somehow?
      var sel = selector_data[i-1];
      if (e.offsetY > sel.top * y_scale && e.offsetY < sel.top * y_scale + sel.height * y_scale
          &&
          e.offsetX > sel.left * y_scale && e.offsetX < sel.left * y_scale + sel.width * y_scale
      ) {
        ctx.strokeRect(sel.left * x_scale, sel.top * y_scale, sel.width * x_scale, sel.height * y_scale);
        // no need to keep digging
        current_selected_i=i;
        break;
      }
    }

  }.debounce(5));

  $('#selector-canvas').bind('mousedown', function (e) {
    alert(selector_data[current_selected_i].xpath);
  });
}
