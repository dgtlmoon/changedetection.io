$(function () {
  // Remove unviewed status when normally clicked
  $('.diff-link').click(function () {
    $(this).closest('.unviewed').removeClass('unviewed');
  });

});


function copyDataToClipBoard(containerid) {
  var range = document.createRange();
  range.selectNode(containerid); //changed here
  window.getSelection().removeAllRanges();
  window.getSelection().addRange(range);
  document.execCommand("copy");
  window.getSelection().removeAllRanges();
}
