(function () {
  "use strict";
  document.addEventListener("DOMContentLoaded", function () {
    var passwordToggle = document.querySelector("[data-password-toggle]");
    var passwordInput = document.getElementById("login-password");
    if (passwordToggle && passwordInput) {
      passwordToggle.addEventListener("click", function () {
        var reveal = passwordInput.type === "password";
        passwordInput.type = reveal ? "text" : "password";
        passwordToggle.textContent = reveal ? "Hide" : "Show";
        passwordToggle.setAttribute("aria-pressed", reveal ? "true" : "false");
        passwordToggle.setAttribute("aria-label", reveal ? "Hide password" : "Show password");
        passwordInput.focus();
      });
    }

    var usernameInput = document.getElementById("login-username");
    var selectionStatus = document.getElementById("demo-selection-status");
    document.querySelectorAll("[data-demo-user]").forEach(function (button) {
      button.addEventListener("click", function () {
        if (!usernameInput) return;
        var username = button.getAttribute("data-demo-user") || "";
        usernameInput.value = username;
        document.querySelectorAll("[data-demo-user]").forEach(function (item) {
          var selected = item === button;
          item.setAttribute("aria-pressed", selected ? "true" : "false");
          item.classList.toggle("selected", selected);
        });
        if (selectionStatus) {
          selectionStatus.textContent = "Username set to " + username + ". Enter the demo password to continue.";
        }
        var password = document.getElementById("login-password");
        if (password) password.focus();
      });
    });
  });
})();
