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
    var password = document.getElementById("login-password");
    var demoPassword = "handover123";

    document.querySelectorAll("[data-demo-user]").forEach(function (button) {
      button.addEventListener("click", function () {
        if (!usernameInput || !password) return;
        var username = button.getAttribute("data-demo-user") || "";
        usernameInput.value = username;
        password.value = demoPassword;

        document.querySelectorAll("[data-demo-user]").forEach(function (item) {
          var selected = item === button;
          item.setAttribute("aria-pressed", selected ? "true" : "false");
          item.classList.toggle("selected", selected);
        });

        if (selectionStatus) {
          selectionStatus.textContent = "Demo credentials filled for " + username + ". Press Sign in to continue.";
          selectionStatus.hidden = false;
        }

        var submit = document.querySelector("#sign-in-form button[type='submit']");
        if (submit) submit.focus();
      });
    });
  });
})();
