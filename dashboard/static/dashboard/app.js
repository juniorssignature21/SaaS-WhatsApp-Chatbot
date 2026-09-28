// Progressive enhancements; every page also works without JavaScript.
(function () {
  // Confirm destructive actions.
  document.addEventListener("submit", function (event) {
    var message = event.target.getAttribute("data-confirm");
    if (message && !window.confirm(message)) event.preventDefault();
  });

  // Clickable table rows.
  document.querySelectorAll("tr[data-href]").forEach(function (row) {
    row.addEventListener("click", function (e) {
      if (e.target.closest("a, button, form")) return;
      window.location = row.getAttribute("data-href");
    });
  });

  // Template parameter inputs follow the chosen template.
  document.querySelectorAll("select[data-template-select]").forEach(function (select) {
    var target = document.getElementById(select.getAttribute("data-template-select"));
    function render() {
      var option = select.options[select.selectedIndex];
      var count = parseInt((option && option.getAttribute("data-params")) || "0", 10);
      var body = (option && option.getAttribute("data-body")) || "";
      target.innerHTML = "";
      if (body) {
        var preview = document.createElement("div");
        preview.className = "help";
        preview.textContent = body;
        target.appendChild(preview);
      }
      for (var i = 1; i <= count; i++) {
        var input = document.createElement("input");
        input.type = "text"; input.name = "params"; input.required = true;
        input.placeholder = "Value for {{" + i + "}}";
        input.style.marginTop = "6px";
        target.appendChild(input);
      }
    }
    select.addEventListener("change", render);
    render();
  });

  // Live conversation updates.
  var thread = document.querySelector("[data-poll-url]");
  if (thread) {
    var url = thread.getAttribute("data-poll-url");
    var lastId = parseInt(thread.getAttribute("data-last-id") || "0", 10);
    var statusEl = document.querySelector("[data-conversation-status]");
    thread.scrollTop = thread.scrollHeight;
    setInterval(function () {
      if (document.hidden) return;
      fetch(url + "?after=" + lastId, { credentials: "same-origin" })
        .then(function (r) { return r.ok ? r.json() : null; })
        .then(function (data) {
          if (!data) return;
          if (data.last_id > lastId) {
            var nearBottom = thread.scrollHeight - thread.scrollTop - thread.clientHeight < 80;
            thread.insertAdjacentHTML("beforeend", data.html);
            lastId = data.last_id;
            if (nearBottom) thread.scrollTop = thread.scrollHeight;
          }
          Object.keys(data.statuses || {}).forEach(function (id) {
            var el = thread.querySelector('[data-status-for="' + id + '"]');
            if (el) el.textContent = data.statuses[id].toLowerCase();
          });
          if (statusEl && statusEl.getAttribute("data-conversation-status") !== data.status_code) {
            window.location.reload();
          }
        })
        .catch(function () {});
    }, 4000);
  }

  // Ctrl/Cmd+Enter submits the composer.
  document.querySelectorAll("textarea[data-submit-on-enter]").forEach(function (area) {
    area.addEventListener("keydown", function (e) {
      if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) area.form.requestSubmit();
    });
  });
})();
