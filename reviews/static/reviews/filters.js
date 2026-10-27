// Narrow the school list to the chosen city/region without a page reload.
// Without JS the server does the same after "Найти" (non-matching options come hidden+disabled).
(function () {
  "use strict";
  function init() {
    var city = document.getElementById("f-city");
    var school = document.getElementById("f-school");
    if (!city || !school) return;
    function apply() {
      var v = city.value, region = "", town = "";
      if (v.indexOf("r:") === 0) region = v.slice(2); else town = v;
      var groups = school.querySelectorAll("optgroup");
      for (var g = 0; g < groups.length; g++) {
        var opts = groups[g].querySelectorAll("option"), visible = 0;
        for (var i = 0; i < opts.length; i++) {
          var o = opts[i];
          var ok = town ? o.getAttribute("data-city") === town
                 : region ? o.getAttribute("data-region") === region : true;
          o.hidden = !ok; o.disabled = !ok;
          if (ok) visible++;
          if (!ok && o.selected) school.value = "";
        }
        groups[g].hidden = visible === 0;
      }
    }
    city.addEventListener("change", apply);
    apply();
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init); else init();
})();
