$(document).ready(function() {

  $('#add-email-helper').click(function (e) {
    e.preventDefault();
    email = prompt("Destination email");
    if(email) {
      var n = $(".notification-urls");
      var p=email_notification_prefix;
      $(n).val( $.trim( $(n).val() )+"\n"+email_notification_prefix+email );
    }
  });

  $('#send-test-notification').click(function (e) {
    e.preventDefault();

    data = {
      notification_body: $('#notification_body').val(),
      notification_format: $('#notification_format').val(),
      notification_title: $('#notification_title').val(),
      notification_urls: $('.notification-urls').val(),
      tags: $('#tags').val(),
      window_url: window.location.href,
    }


    $.ajax({
      type: "POST",
      url: notification_base_url,
      data : data,
        statusCode: {
        400: function(data) {
          // More than likely the CSRF token was lost when the server restarted
          alert(data.responseText);
        }
      }
    }).done(function(data){
      console.log(data);
      alert(data);
    })
  });
});

