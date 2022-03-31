$(function () {
  // Remove unviewed status when normally clicked
  $('.diff-link').click(function () {
    $(this).closest('.unviewed').removeClass('unviewed');
  });
});
