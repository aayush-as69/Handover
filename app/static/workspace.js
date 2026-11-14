(function () {
  "use strict";
  document.addEventListener("DOMContentLoaded", function () {
    document.querySelectorAll("[data-live-search]").forEach(function (input) {
      var targetSelector = input.getAttribute("data-search-target");
      var target = targetSelector ? document.querySelector(targetSelector) : null;
      if (!target) return;
      var selector = input.getAttribute("data-search-items") || "[data-search-item]";
      var items = Array.prototype.slice.call(target.querySelectorAll(selector));
      var count = input.getAttribute("data-search-count");
      var countNode = count ? document.querySelector(count) : null;
      var empty = target.querySelector("[data-search-empty]");

      function filter() {
        var query = input.value.trim().toLocaleLowerCase();
        var shown = 0;
        items.forEach(function (item) {
          var text = (item.innerText || item.textContent || "").toLocaleLowerCase();
          var match = !query || text.indexOf(query) !== -1;
          item.hidden = !match;
          if (match) shown += 1;
        });
        if (countNode) countNode.textContent = query ? shown + " shown / " + items.length : items.length + " item(s)";
        if (empty) empty.hidden = shown !== 0 || items.length === 0;
      }
      input.addEventListener("input", filter);
      input.addEventListener("search", filter);
      filter();
    });

    document.querySelectorAll("[data-file-drop]").forEach(function (zone) {
      var input = zone.querySelector('input[type="file"]');
      var name = zone.querySelector("[data-file-name]");
      if (!input) return;
      function updateName() {
        if (name) name.textContent = input.files && input.files.length ? input.files[0].name : "Choose a file or drop it here";
        zone.classList.toggle("has-file", !!(input.files && input.files.length));
      }
      input.addEventListener("change", updateName);
      ["dragenter", "dragover"].forEach(function (eventName) {
        zone.addEventListener(eventName, function (event) {
          event.preventDefault();
          zone.classList.add("is-dragover");
        });
      });
      ["dragleave", "drop"].forEach(function (eventName) {
        zone.addEventListener(eventName, function (event) {
          event.preventDefault();
          zone.classList.remove("is-dragover");
        });
      });
      zone.addEventListener("drop", function (event) {
        if (!event.dataTransfer || !event.dataTransfer.files.length) return;
        try {
          input.files = event.dataTransfer.files;
          updateName();
        } catch (e) {
          if (name) name.textContent = "Use the file picker to select this file";
        }
      });
      updateName();
    });

    var path = window.location.pathname.replace(/\/$/, "") || "/";
    document.querySelectorAll(".workspace-nav a").forEach(function (link) {
      var href = link.getAttribute("href") || "";
      var exact = href === path;
      var nested = href !== "/" && path.indexOf(href + "/") === 0;
      if (exact || nested) {
        link.setAttribute("aria-current", "page");
      } else {
        link.removeAttribute("aria-current");
      }
    });
  });
})();

document.addEventListener("click", function (event) {
  var all = event.target.closest("[data-select-all]");
  var none = event.target.closest("[data-select-none]");
  if (!all && !none) return;
  var form = event.target.closest("form");
  if (!form) return;
  form.querySelectorAll('input[type="checkbox"]').forEach(function (box) { box.checked = !!all; });
});

document.addEventListener("click", function (event) {
  document.querySelectorAll("details.more[open]").forEach(function (menu) {
    if (!menu.contains(event.target) || event.target === menu) menu.open = false;   // outside, or the dimmed backdrop
  });
});
document.addEventListener("keydown", function (event) {
  if (event.key !== "Escape") return;
  document.querySelectorAll("details.more[open]").forEach(function (menu) { menu.open = false; });
});
