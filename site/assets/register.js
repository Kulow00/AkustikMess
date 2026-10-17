// Lizenzanfrage: sendet Name/E-Mail/Angaben an /api/request (gleicher Server, kein Drittanbieter).
"use strict";
(function () {
  const card = document.getElementById("regCard");
  if (card.dataset.enabled !== "true") {
    card.classList.add("hidden");
    document.getElementById("regSoon").classList.remove("hidden");
    return;
  }
  const form = document.getElementById("regForm"), msg = document.getElementById("regMsg");
  const btn = document.getElementById("regSend");
  function show(text, ok) { msg.textContent = text; msg.className = "msg " + (ok ? "ok" : "err"); }
  form.addEventListener("submit", async (ev) => {
    ev.preventDefault();
    const name = form.name.value.trim(), email = form.email.value.trim();
    if (name.length < 2) return show("Bitte einen Namen angeben.", false);
    if (!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(email)) return show("Bitte eine gültige E-Mail-Adresse angeben.", false);
    if (!form.consent.checked) return show("Bitte der Datenschutzerklärung zustimmen.", false);
    btn.disabled = true;
    show("Wird gesendet …", true);
    try {
      const r = await fetch("api/request", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name, email, message: form.message.value.trim(), consent: true,
                               website: form.website.value })
      });
      const res = await r.json().catch(() => ({}));
      if (!r.ok) { show(res.error || "Fehler " + r.status, false); btn.disabled = false; return; }
      show("Danke! Deine Anfrage ist eingegangen. Du bekommst eine Bestätigung per E-Mail und nach der Freigabe " +
           "deinen Lizenzschlüssel mit Download-Link.", true);
      form.classList.add("hidden");
    } catch (e) {
      show("Server nicht erreichbar. Bitte später erneut versuchen.", false);
      btn.disabled = false;
    }
  });
})();
