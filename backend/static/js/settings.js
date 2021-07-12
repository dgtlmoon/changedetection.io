window.addEventListener("load", (event) => {
  function toggleTable() {
    var x = document.getElementById("token-table");
    if (x.style.display === "table") {
      x.style.display = "none";
    } else {
      x.style.display = "table";
    }
  }
  document.getElementById("show-token-table").onclick = function() {
      toggleTable();
  }

  // just an example for now
  function toggleVisible(elem) {
  // theres better ways todo this
    var x = document.getElementById(notification-customisation);
    if (x.style.display === "block") {
      x.style.display = "none";
    } else {
      x.style.display = "block";
    }
  }
  document.getElementById("settings-customise-notifications").onclick = function() {
      toggleVisible('notification-customisation');
  }

});
