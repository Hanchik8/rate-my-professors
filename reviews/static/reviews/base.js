(function () {
  "use strict";
  document.documentElement.classList.remove("no-js");
  var toggle = document.querySelector(".nav-toggle");
  if (!toggle) { return; }
  toggle.addEventListener("click", function () {
    var open = toggle.getAttribute("aria-expanded") === "true";
    toggle.setAttribute("aria-expanded", String(!open));
    var nav = document.getElementById(toggle.getAttribute("aria-controls"));
    if (nav) { nav.classList.toggle("open", !open); }
  });
  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape" && toggle.getAttribute("aria-expanded") === "true") {
      toggle.setAttribute("aria-expanded", "false");
      var nav = document.getElementById(toggle.getAttribute("aria-controls"));
      if (nav) { nav.classList.remove("open"); }
      toggle.focus();
    }
  });
})();
