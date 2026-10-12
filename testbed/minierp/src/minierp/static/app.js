// MiniERP page behaviour. The server decides the chaos for each page view and passes it
// in data attributes on <body>; this script only acts it out.
(() => {
  "use strict";

  const body = document.body;
  const loadDelay = Number.parseInt(body.dataset.loadDelayMs || "0", 10);
  const popupDelay = Number.parseInt(body.dataset.sessionPopupMs || "-1", 10);

  function finishLoading() {
    document.getElementById("loading").hidden = true;
    document.getElementById("main").hidden = false;
  }

  function showSessionPopup() {
    const backdrop = document.createElement("div");
    backdrop.className = "backdrop";
    backdrop.innerHTML =
      '<div role="dialog" aria-modal="true" aria-labelledby="session-title" class="modal">' +
      '<h2 id="session-title">Session expiring</h2>' +
      "<p>Your session will expire soon. Do you want to stay signed in?</p>" +
      '<div class="actions"><button type="button" id="session-continue">Continue</button></div>' +
      "</div>";
    document.body.appendChild(backdrop);
    const button = backdrop.querySelector("button");
    button.focus();
    button.addEventListener("click", async () => {
      try {
        await fetch("/session/keepalive", { method: "POST" });
      } finally {
        backdrop.remove();
      }
    });
  }

  if (loadDelay > 0) {
    setTimeout(finishLoading, loadDelay);
  }
  if (popupDelay >= 0) {
    setTimeout(showSessionPopup, Math.max(loadDelay, 0) + popupDelay);
  }
})();
