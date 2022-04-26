$(function () {
  // Remove unviewed status when normally clicked
  $('.diff-link').click(function () {
    $(this).closest('.unviewed').removeClass('unviewed');
  });

  // after page fetch, inject this JS
  // build a map of all elements and their positions (maybe that only include text?)
  var p = $( "*" );
  for (var i = 0; i < p.length; i++) {
     console.log($(p[i]).offset());
     console.log($(p[i]).width());
     console.log($(p[i]).height());
     console.log(getXPath( p[i]));
  }

  // overlay it on a rendered image of the page



  //p.html( "left: " + offset.left + ", top: " + offset.top );
});
