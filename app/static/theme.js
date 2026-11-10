// Light/dark theme: follows the device until the person picks one; the choice is remembered.
(function () {
  var root = document.documentElement, KEY = "handover-theme", stored = null;
  try { stored = localStorage.getItem(KEY); } catch (e) {}
  var dark = window.matchMedia ? window.matchMedia("(prefers-color-scheme: dark)") : null;
  function current() { return stored || (dark && dark.matches ? "dark" : "light"); }
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
  if (dark && dark.addEventListener) dark.addEventListener("change", function () { if (!stored) apply(); });
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
