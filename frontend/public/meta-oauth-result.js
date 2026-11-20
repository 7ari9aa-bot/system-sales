// Delivers the Meta OAuth outcome from the popup back to the settings page.
// Loaded as an external same-origin file on purpose: the site CSP is
// `script-src 'self'` (Vercel stamps it on every path, including the proxied
// /api/v1/... callback), so an inline script on the result page is blocked.
(function () {
  var dataEl = document.getElementById("meta-oauth-data");
  if (!dataEl) return;
  var msg;
  try {
    msg = JSON.parse(dataEl.textContent || "{}");
  } catch (_) {
    return;
  }
  var origin = dataEl.getAttribute("data-origin") || "*";

  if (window.opener) {
    try {
      window.opener.postMessage(msg, origin);
    } catch (e) {
      try { window.opener.postMessage(msg, "*"); } catch (_) {}
    }
  }

  try {
    var bc = new BroadcastChannel("meta_oauth");
    bc.postMessage(msg);
  } catch (_) {}

  try {
    localStorage.setItem("meta_oauth_result", JSON.stringify(msg));
  } catch (_) {}

  if (dataEl.getAttribute("data-autoclose") === "1") {
    setTimeout(function () { window.close(); }, 1400);
  }
  var closeBtn = document.getElementById("meta-oauth-close");
  if (closeBtn) closeBtn.addEventListener("click", function () { window.close(); });
})();
