$(document).ready(function() {
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
        window_url : window.location.href,
        notification_urls : $('#notification_urls').val(),
        notification_title : $('#notification_title').val(),
        notification_body : $('#notification_body').val(),
        notification_format : $('#notification_format').val(),
    }
    for (key in data) {
      if (!data[key].length) {
        alert(key+" is empty, cannot send test.")
        return;
      }
    }

    $.ajax({
      type: "POST",
      url: '/notification/send-test',
      data : data
    }).done(function(data){
      console.log(data);
      alert('Sent');
    }).fail(function(data){
      console.log(data);
      alert('Error: '+data.responseJSON.error);
    })
  });
});

