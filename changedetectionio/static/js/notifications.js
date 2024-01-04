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

    // this can be global
    var csrftoken = $('input[name=csrf_token]').val();
    $.ajaxSetup({
        beforeSend: function(xhr, settings) {
            if (!/^(GET|HEAD|OPTIONS|TRACE)$/i.test(settings.type) && !this.crossDomain) {
                xhr.setRequestHeader("X-CSRFToken", csrftoken)
            }
        }
    })

    data = {
      notification_body: $('#notification_body').val(),
      notification_format: $('#notification_format').val(),
      notification_title: $('#notification_title').val(),
      notification_urls: $('.notification-urls').val(),
      window_url: window.location.href,
    }


    if (!data['notification_urls'].length) {
      alert("Notification URL list is empty, cannot send test.")
      return;
    }

    $.ajax({
      type: "POST",
      url: notification_base_url,
      data : data,
        statusCode: {
        400: function() {
            // More than likely the CSRF token was lost when the server restarted
          alert("There was a problem processing the request, please reload the page.");
        }
      }
    }).done(function(data){
      console.log(data);
      alert('Sent');
    }).fail(function(data){
      console.log(data);
      alert('There was an error communicating with the server.');
    })
  });
});

