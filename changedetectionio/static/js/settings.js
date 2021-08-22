window.addEventListener("load", (event) => {
  // just an example for now
  function toggleVisible(elem) {
    // theres better ways todo this
    var x = document.getElementById(elem);
    if (x.style.display === "block") {
      x.style.display = "none";
    } else {
      x.style.display = "block";
    }
  }
});

