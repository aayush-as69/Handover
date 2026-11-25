// Guided tour: one step at a time, with a few things to click. The page reads fine without this
// script (every step is shown in order); the script only adds navigation and the interactions.
(function () {
  "use strict";
  document.addEventListener("DOMContentLoaded", function () {
    var root = document.querySelector("[data-tour]");
    if (!root) return;
    root.classList.add("js");

    var steps = Array.prototype.slice.call(root.querySelectorAll(".tour-step"));
    var links = Array.prototype.slice.call(root.querySelectorAll(".tour-rail a"));
    var prev = root.querySelector("[data-prev]");
    var next = root.querySelector("[data-next]");
    var progress = root.querySelector("[data-progress]");
    var current = -1;

    function fromHash() {
      var m = /^#step-(\d+)$/.exec(window.location.hash);
      var n = m ? parseInt(m[1], 10) - 1 : 0;
      return n >= 0 && n < steps.length ? n : 0;
    }

    function show(n, moveFocus) {
      if (n < 0 || n >= steps.length) return;
      current = n;
      steps.forEach(function (step, i) { step.hidden = i !== n; });
      links.forEach(function (a, i) {
        if (i === n) a.setAttribute("aria-current", "step"); else a.removeAttribute("aria-current");
      });
      prev.disabled = n === 0;
      next.hidden = n === steps.length - 1;
      progress.textContent = "Step " + (n + 1) + " of " + steps.length;
      try { history.replaceState(null, "", "#step-" + (n + 1)); } catch (e) {}
      if (moveFocus) {
        var h = steps[n].querySelector("h2");
        if (h) h.focus({ preventScroll: true });
        var top = root.querySelector(".tour-layout").getBoundingClientRect().top + window.scrollY - 80;
        window.scrollTo({ top: Math.max(0, top), behavior: "auto" });
      }
    }

    links.forEach(function (a, i) {
      a.addEventListener("click", function (e) { e.preventDefault(); show(i, true); });
    });
    prev.addEventListener("click", function () { show(current - 1, true); });
    next.addEventListener("click", function () { show(current + 1, true); });
    window.addEventListener("hashchange", function () { show(fromHash(), false); });
    document.addEventListener("keydown", function (e) {
      if (e.altKey || e.ctrlKey || e.metaKey || e.shiftKey) return;
      var t = e.target && e.target.tagName;
      if (t === "INPUT" || t === "TEXTAREA" || t === "SELECT") return;
      if (e.key === "ArrowRight") show(current + 1, true);
      else if (e.key === "ArrowLeft") show(current - 1, true);
    });

    // Switches: buttons that choose which panel is visible.
    Array.prototype.forEach.call(root.querySelectorAll("[data-switch]"), function (sw) {
      var buttons = Array.prototype.slice.call(sw.querySelectorAll("button[data-show]"));
      function choose(btn) {
        buttons.forEach(function (b) {
          var on = b === btn;
          b.setAttribute("aria-pressed", on ? "true" : "false");
          var panel = document.getElementById(b.getAttribute("data-show"));
          if (panel) panel.hidden = !on;
        });
      }
      buttons.forEach(function (b) { b.addEventListener("click", function () { choose(b); }); });
      choose(buttons[0]);
    });

    // Step 4: approve, edit, reject, reopen.
    var decide = root.querySelector("[data-decide]");
    if (decide) {
      var pill = decide.querySelector("[data-status]");
      var message = decide.querySelector("[data-message]");
      var outcomes = {
        approve: ["approved", "verified", "Approved. This claim goes into the next release."],
        edit: ["edited", "inferred", "Edited. It is checked against its quote again and needs approval again before it goes anywhere."],
        reject: ["rejected", "conflicting", "Rejected. It stays on record but never reaches a release."],
        reset: ["generated", "inferred", "Nothing has been decided yet. This claim stays out of every release until someone does."]
      };
      Array.prototype.forEach.call(decide.querySelectorAll("[data-action]"), function (b) {
        b.addEventListener("click", function () {
          var o = outcomes[b.getAttribute("data-action")];
          pill.textContent = o[0];
          pill.className = "pill " + o[1];
          message.textContent = o[2];
        });
      });
    }

    show(fromHash(), false);
  });
})();
