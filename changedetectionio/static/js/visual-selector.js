$("img#selector-background").bind('load', function () {
  // Image is ready
  $('.fetching-update-notice').html("Fetching element data..");

  $.ajax({
    url: watch_visual_selector_data_url,
    context: document.body
  }).done(function (data) {
    $('.fetching-update-notice').html("Rendering..");
    reflow_selector(data);
  });

});

function reflow_selector(selector_data) {
  $('#selector-canvas').attr('width', $("img#selector-background").width());
  $('#selector-canvas').attr('height', $("img#selector-background").height());

  //.attr('height', $("img#selector-background").height());

  // could trim it according to the lowest/furtheret item in the dataset
  stage = new createjs.Stage("selector-canvas");

  // to get onMouseOver & onMouseOut events, we need to enable them on the
  // stage:
  stage.enableMouseOver();
  output = new createjs.Text("Test press, click, doubleclick, mouseover, and mouseout", "14px Arial");
  output.x = output.y = 10;
  stage.addChild(output);

  var squares = [];
  for (var i = 0; i < selector_data.length; i++) {

    squares[i] = new createjs.Shape();

    squares[i].graphics.beginFill("rgba(215,0,0,0.2)").drawRect(
        selector_data[i]['left'],
        selector_data[i]['top'],
        selector_data[i]['width'],
        selector_data[i]['height']);
    
    squares[i].name = selector_data[i]['xpath'];
    stage.addChild(squares[i]);

    squares[i].on("click", handleMouseEvent);
    squares[i].on("dblclick", handleMouseEvent);
    squares[i].on("mouseover", handleMouseEvent);
    squares[i].on("mouseout", handleMouseEvent);
    squares.push(squares[i]);
  }


  stage.update();
  $('.fetching-update-notice').hide();
}

function handleMouseEvent(evt) {
  output.text = "evt.target: " + evt.target + ", evt.type: " + evt.type;

  if(evt.type == 'mouseover') {
    evt.target.graphics.beginFill("rgba(225,220,220,0.9)");
  }

  if(evt.type == 'mouseout') {
    evt.target.graphics.beginFill("rgba(1,1,1,0.4)");
  }

  // to save CPU, we're only updating when we need to, instead of on a tick:1
  stage.update();
}
