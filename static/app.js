(function () {
  // Filters: open on desktop, collapsed on phones so results come first.
  var filters = document.getElementById("filters");
  if (filters && window.matchMedia("(max-width: 899px)").matches) {
    filters.open = false;
  }

  // Optional "remember my key": kept only in this browser's own storage, never sent to or stored by the
  // server except inside the one request that uses it. Storage can be blocked, so every access is guarded.
  var KEYS = "scholarly.keys";
  function readKeys() {
    try { return JSON.parse(localStorage.getItem(KEYS) || "{}") || {}; } catch (e) { return {}; }
  }
  function writeKeys(obj) {
    try { localStorage.setItem(KEYS, JSON.stringify(obj)); } catch (e) { /* storage blocked: ignore */ }
  }
  document.querySelectorAll("form").forEach(function (form) {
    var keyInput = form.querySelector("input[name=api_key]");
    var remember = form.querySelector("[data-remember-key]");
    if (!keyInput || !remember) { return; }
    var provider = form.querySelector("select[name=provider]");
    var forget = form.querySelector("[data-forget-key]");
    var note = form.querySelector("[data-key-note]");
    function current() { return provider ? provider.value : "gemini"; }
    function fill() {
      var saved = readKeys()[current()];
      if (saved && !keyInput.value) { keyInput.value = saved; }
      var box = form.querySelector("details.byo");
      if (saved && box) { box.open = true; }
      remember.checked = !!saved;
      if (forget) { forget.hidden = !saved; }
      if (note) { note.textContent = saved ? "A key is saved on this device." : ""; }
    }
    if (provider) {
      provider.addEventListener("change", function () { keyInput.value = ""; fill(); });
    }
    form.addEventListener("submit", function () {
      var all = readKeys();
      var value = keyInput.value.trim();
      if (remember.checked && value) { all[current()] = value; } else { delete all[current()]; }
      writeKeys(all);
    });
    if (forget) {
      forget.addEventListener("click", function () {
        var all = readKeys();
        delete all[current()];
        writeKeys(all);
        keyInput.value = "";
        fill();
      });
    }
    fill();
  });

  // Slow forms (essay feedback): show that it is working and stop double submits.
  document.querySelectorAll("form[data-busy]").forEach(function (form) {
    form.addEventListener("submit", function () {
      var btn = form.querySelector("button[type=submit]");
      if (btn) {
        btn.disabled = true;
        btn.classList.add("is-busy");
        btn.textContent = form.dataset.busy;
      }
    });
  });

  // Admin: while an AI update is running, check its status and reload when it ends.
  var box = document.querySelector("[data-run-status]");
  if (box) {
    var poll = function () {
      fetch(box.dataset.url, { credentials: "same-origin" })
        .then(function (r) { return r.json(); })
        .then(function (d) {
          if (d.status !== "running") { window.location.reload(); }
          else { setTimeout(poll, 4000); }
        })
        .catch(function () { setTimeout(poll, 8000); });
    };
    setTimeout(poll, 3000);
  }
})();
