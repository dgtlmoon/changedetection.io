var timer = setInterval(function() {

	var url = location.protocol + '//' + location.host + '/api/queue-status';
	var xhr = new XMLHttpRequest();
	xhr.onreadystatechange = function() {
		if (xhr.readyState == XMLHttpRequest.DONE) {
			document.getElementById("queue-status").innerHTML = "Queue: " + xhr.responseText;
		}
	}
	xhr.open('GET', url);
	xhr.send(null);

}, 250);