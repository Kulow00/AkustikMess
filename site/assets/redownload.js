// „Ich habe eine Lizenz“: Lizenzschlüssel oder E-Mail + Lizenz-ID → einmaliger Download-Link vom Lizenzserver.
"use strict";
(function () {
  const form = document.getElementById("redl");
  if (!form) return;
  const msg = document.getElementById("rdMsg"), btn = document.getElementById("rdSend");
  function show(text, ok) { msg.textContent = text; msg.className = "msg " + (ok ? "ok" : "err"); }
  form.addEventListener("submit", async (ev) => {
    ev.preventDefault();
    const key = document.getElementById("rdKey").value.replace(/\s+/g, "");
    const email = document.getElementById("rdMail").value.trim(), id = document.getElementById("rdId").value.trim();
    const body = key ? { license: key } : { email, id };
    if (!key && (!email || !id)) return show("Bitte Lizenzschlüssel oder E-Mail-Adresse und Lizenz-ID eingeben.", false);
    btn.disabled = true;
    show("Wird geprüft …", true);
    try {
      const r = await fetch("api/redownload", { method: "POST", headers: { "Content-Type": "application/json" },
                                                body: JSON.stringify(body) });
      const res = await r.json().catch(() => ({}));
      if (!r.ok || !res.url) { show(res.error || "Fehler " + r.status, false); btn.disabled = false; return; }
      window.location.href = res.url;
    } catch (e) {
      show("Server nicht erreichbar. Bitte später erneut versuchen.", false);
      btn.disabled = false;
    }
  });
})();
