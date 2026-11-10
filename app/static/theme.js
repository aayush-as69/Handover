// Light/dark theme: dark by default; the person's choice is remembered in this browser.
(function () {
  var root = document.documentElement, KEY = "handover-theme", stored = null;
  try { stored = localStorage.getItem(KEY); } catch (e) {}
  function current() { return stored === "light" ? "light" : "dark"; }
  function apply() {
    root.setAttribute("data-theme", current());
    var b = document.getElementById("theme-toggle");
    if (b) {
      var next = current() === "dark" ? "light" : "dark";
      b.setAttribute("aria-label", "Switch to " + next + " theme");
      b.setAttribute("title", "Switch to " + next + " theme");
    }
  }
  apply();
  document.addEventListener("DOMContentLoaded", function () {
    apply();
    var b = document.getElementById("theme-toggle");
    if (!b) return;
    b.addEventListener("click", function () {
      stored = current() === "dark" ? "light" : "dark";
      try { localStorage.setItem(KEY, stored); } catch (e) {}
      apply();
    });
  });
})();
