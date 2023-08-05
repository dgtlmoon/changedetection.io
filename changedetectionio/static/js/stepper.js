$(document).ready(function(){
   checkUserVal();
   $('#fetch_backend input').on('change', checkUserVal);
});

var checkUserVal = function(){
    if($('#fetch_backend input:checked').val()=='html_requests') {
      $('#request-override').show();
      $('#webdriver-stepper').hide();
    } else {
      $('#request-override').hide();
      $('#webdriver-stepper').show();
    }
};

$('a.row-options').on('click', function(){
    var row=$(this.closest('tr'));
    switch($(this).data("action")) {
      case 'remove':
        $(row).remove();
      break;
      case 'add':
        var new_row=$(row).clone(true).insertAfter($(row));
        $('input', new_new).val("");
      break;
      case 'add':
        var new_row=$(row).clone(true).insertAfter($(row));
        $('input', new_new).val("");
      break;
      case 'resend-step':

      break;
    }
});