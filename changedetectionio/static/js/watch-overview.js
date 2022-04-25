$(function () {
  // Remove unviewed status when normally clicked
  $('.diff-link').click(function () {
    $(this).closest('.unviewed').removeClass('unviewed');
  });

  $('.with-share-link > *').click(function () {
      $("#copied-clipboard").remove();

      var range = document.createRange();
      var n=$("#share-link")[0];
      range.selectNode(n);
      window.getSelection().removeAllRanges();
      window.getSelection().addRange(range);
      document.execCommand("copy");
      window.getSelection().removeAllRanges();

      $('.with-share-link').append('<span style="font-size: 80%; color: #fff;" id="copied-clipboard">Copied to clipboard</span>');
      $("#copied-clipboard").fadeOut(2500, function() {
       $(this).remove();
      });
  });
});

