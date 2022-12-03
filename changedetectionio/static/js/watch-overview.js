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

    // checkboxes - check all
    $("#check-all").click(function (e) {
        $('input[type=checkbox]').not(this).prop('checked', this.checked);
    });
    // checkboxes - show/hide buttons
    $("input[type=checkbox]").click(function (e) {
        if ($('input[type=checkbox]:checked').length) {
            $('#checkbox-operations').slideDown();
        } else {
            $('#checkbox-operations').slideUp();
        }
    });

});

