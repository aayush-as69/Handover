(function () {
  "use strict";
  document.addEventListener("DOMContentLoaded", function () {
    var toggle = document.querySelector("[data-password-toggle]");
    var input = document.getElementById("login-password");
    if (!toggle || !input) return;

    toggle.addEventListener("click", function () {
      var reveal = input.type === "password";
      input.type = reveal ? "text" : "password";
      toggle.textContent = reveal ? "Hide" : "Show";
      toggle.setAttribute("aria-pressed", reveal ? "true" : "false");
      toggle.setAttribute("aria-label", reveal ? "Hide password" : "Show password");
      input.focus();
    });
  });
})();
