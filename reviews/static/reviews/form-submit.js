(function () {
  "use strict";

  var BUSY_CLASS = "is-loading";
  var BUSY_ATTR = "submitState";

  function findSubmitter(form, event) {
    if (event.submitter && form.contains(event.submitter)) { return event.submitter; }
    return form.querySelector('button[type="submit"], button:not([type])');
  }

  function blockSubmitter(button) {
    if (!button || button.tagName !== "BUTTON" || button.disabled) { return; }
    button.classList.add(BUSY_CLASS);
    button.setAttribute("aria-busy", "true");
    button.disabled = true;
  }

  function preserveSubmitterValue(form, button) {
    if (!button.name) { return; }
    var value = document.createElement("input");
    value.type = "hidden";
    value.name = button.name;
    value.value = button.value || "";
    value.setAttribute("data-submit-state-value", "true");
    form.appendChild(value);
  }

  function resetForm(form) {
    delete form.dataset[BUSY_ATTR];
    Array.prototype.forEach.call(
      form.querySelectorAll("." + BUSY_CLASS),
      function (button) {
        button.disabled = false;
        button.classList.remove(BUSY_CLASS);
        button.removeAttribute("aria-busy");
      }
    );
    Array.prototype.forEach.call(
      form.querySelectorAll("[data-submit-state-value]"),
      function (input) { input.remove(); }
    );
  }

  document.addEventListener("submit", function (event) {
    var form = event.target;
    if (!(form instanceof HTMLFormElement) || event.defaultPrevented) { return; }
    if (form.dataset[BUSY_ATTR] === "true") { event.preventDefault(); return; }
    form.dataset[BUSY_ATTR] = "true";

    var button = findSubmitter(form, event);
    if (!button) { return; }
    preserveSubmitterValue(form, button);
    blockSubmitter(button);
  });

  document.addEventListener("reset", function (event) {
    if (event.target instanceof HTMLFormElement) { resetForm(event.target); }
  });

  window.addEventListener("pageshow", function (event) {
    if (!event.persisted) { return; }
    Array.prototype.forEach.call(document.forms, resetForm);
  });
})();
