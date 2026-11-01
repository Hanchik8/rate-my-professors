(function () {
  "use strict";

  var button = document.querySelector("[data-share-button]");
  if (!button) { return; }

  var field = document.querySelector("[data-share-field]");
  var status = document.querySelector("[data-share-status]");
  var url = button.getAttribute("data-share-url") || (field ? field.value : window.location.href);
  var copiedLabel = button.getAttribute("data-share-copied") || "";

  // Without JS the button stays hidden and the read-only URL field is the fallback.
  button.hidden = false;

  function announceCopied() {
    if (!status || !copiedLabel) { return; }
    status.textContent = copiedLabel;
    status.hidden = false;
  }

  function copyWithField() {
    if (!field) { return false; }
    field.focus();
    field.select();
    try {
      return document.execCommand("copy");
    } catch (err) {
      return false;
    }
  }

  button.addEventListener("click", function () {
    if (navigator.clipboard && window.isSecureContext) {
      navigator.clipboard.writeText(url).then(announceCopied, function () {
        if (copyWithField()) { announceCopied(); }
      });
    } else if (copyWithField()) {
      announceCopied();
    }
  });
})();
