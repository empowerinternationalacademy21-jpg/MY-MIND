/* MyMind — caretaker 18+ verification page (no inline scripts: CSP-safe).
   FLOW: form -> POST /verify/start (server age gate, then Sumsub applicant + access token) -> mount Sumsub WebSDK with that token
         -> when the SDK says "submitted", poll /verify/status until the SERVER (which hears from Sumsub) says verified / rejected.
   The page never decides that someone is verified: it only shows what the server reports. */
(function () {
  "use strict";
  const root = document.getElementById("verify");
  if (!root) return;
  const $ = (id) => document.getElementById(id);
  const form = $("vf-form"), errBox = $("vf-error"), submit = $("vf-submit"), underage = $("vf-underage"), status = $("vf-status");
  const csrf = (document.querySelector('meta[name="csrf"]') || {}).content || "";
  let sdkLoaded = false, polling = null, pollCount = 0;

  const show = (el, on) => { el.hidden = !on; };
  async function post(url, body) {
    const r = await fetch(url, { method: "POST", credentials: "same-origin", headers: { "Content-Type": "application/json", "X-CSRFToken": csrf, Accept: "application/json" }, body: JSON.stringify(body || {}) });
    let data = {}; try { data = await r.json(); } catch (e) { }
    return { ok: r.ok, status: r.status, data };
  }
  function fail(msg, field) {
    errBox.textContent = msg; show(errBox, true);
    [...form.querySelectorAll("input")].forEach((i) => i.removeAttribute("aria-invalid"));
    if (field && $(field)) { $(field).setAttribute("aria-invalid", "true"); $(field).focus(); } else errBox.scrollIntoView({ block: "nearest" });
  }
  function stop(msg) {                                   // the gentle but firm "Access denied" state
    show(form, false); show($("vf-sdk-wrap"), false); show(status, false);
    $("vf-underage-msg").textContent = msg; show(underage, true); underage.focus();
  }
  function info(title, msg, retry) {
    $("vf-status-title").textContent = title; $("vf-status-msg").textContent = msg; show($("vf-retry"), !!retry);
    show(status, true); status.focus({ preventScroll: false });
  }

  /* ---------- Sumsub WebSDK ---------- */
  function loadSdk() {
    return new Promise((resolve, reject) => {
      if (sdkLoaded || window.snsWebSdk) { sdkLoaded = true; return resolve(); }
      const s = document.createElement("script"); s.src = root.dataset.sdkUrl; s.async = true;
      s.onload = () => { sdkLoaded = true; resolve(); }; s.onerror = () => reject(new Error("sdk"));
      document.head.appendChild(s);
    });
  }
  async function freshToken() {                          // called by the SDK when its token expires
    const r = await post("/verify/token");
    if (!r.ok) throw new Error(r.data.message || "token");
    return r.data.token;
  }
  async function launch(token) {
    show(form, false); show(status, false);
    try { await loadSdk(); } catch (e) { show(form, true); return fail("We couldn't load the ID check. Please check your connection and try again."); }
    show($("vf-sdk-wrap"), true); $("sumsub-websdk-container").replaceChildren();
    const sdk = window.snsWebSdk.init(token, freshToken)
      .withConf({ lang: document.documentElement.lang || "en" })
      .withOptions({ addViewportTag: false, adaptIframeHeight: true })
      .on("idCheck.onApplicantSubmitted", () => { show($("vf-sdk-wrap"), false); info("Thank you", "We're checking your ID now. This usually takes a minute or two. You can keep this page open."); startPolling(); })
      .on("idCheck.onApplicantStatusChanged", (p) => { if (p && p.reviewStatus === "completed") startPolling(); })
      .on("idCheck.onError", () => { /* the SDK shows its own error UI; the server remains the judge */ })
      .build();
    sdk.launch("#sumsub-websdk-container");
  }

  /* ---------- waiting for the server's verdict ---------- */
  function startPolling() {
    if (polling) return; pollCount = 0; tick();
    polling = setInterval(tick, 5000);
  }
  async function tick() {
    pollCount++;
    try {
      const r = await fetch("/verify/status", { credentials: "same-origin", headers: { Accept: "application/json" } });
      const d = await r.json();
      if (d.state === "verified") { clearInterval(polling); polling = null; info("You're verified", "Thank you. Taking you to the next step."); setTimeout(() => { location.href = d.next || "/"; }, 1200); return; }
      if (d.state === "retry") { clearInterval(polling); polling = null; info("Let's try that again", "We couldn't read your ID clearly. Please take a new photo in good light.", true); return; }
      if (d.state === "rejected") { clearInterval(polling); polling = null; info("We couldn't verify you", "Please contact the administrator and they will help you. Nothing has been shared with anyone.", false); return; }
      if (d.state === "blocked") { clearInterval(polling); polling = null; stop("MyMind accounts are for adults who care for a child, so the person creating one must be 18 or older. Please ask a parent, guardian or caretaker to set it up."); return; }
    } catch (e) { /* keep waiting */ }
    if (pollCount > 60) { clearInterval(polling); polling = null; info("Still checking", "This is taking longer than usual. You can close this page: your account opens as soon as the check is done. Come back and refresh to see the result."); }
  }
  $("vf-retry").addEventListener("click", async () => {
    $("vf-retry").disabled = true;
    try { await launch(await freshToken()); } catch (e) { info("Please try again", "We couldn't restart the check. Please refresh the page.", false); }
    $("vf-retry").disabled = false;
  });

  /* ---------- the form ---------- */
  form.addEventListener("submit", async (e) => {
    e.preventDefault(); show(errBox, false);
    const body = { full_name: $("vf-name").value.trim(), email: $("vf-email").value.trim(), dob: $("vf-dob").value, consent: $("vf-consent").checked };
    if (body.full_name.length < 2) return fail("Please enter your full name.", "vf-name");
    if (!/^\S+@\S+\.\S+$/.test(body.email)) return fail("Please enter a valid email address.", "vf-email");
    if (!body.dob) return fail("Please enter your date of birth.", "vf-dob");
    if (!body.consent) return fail("Please tick the box to agree to the identity check.", "vf-consent");
    submit.disabled = true; submit.textContent = "One moment…";
    try {
      const r = await post("/verify/start", body);
      if (r.status === 403 && r.data.error === "underage") return stop(r.data.message);
      if (!r.ok) return fail(r.data.message || "Something went wrong. Please try again.", r.data.error === "invalid" ? "vf-dob" : null);
      if (r.data.state === "verified") { location.href = r.data.next || "/"; return; }
      if (r.data.mode === "demo") { show(form, false); show($("vf-demo"), true); return; }
      await launch(r.data.token);
    } catch (err) { fail("We couldn't reach MyMind. Please check your connection and try again."); }
    finally { submit.disabled = false; submit.textContent = "Continue"; }
  });
  const demoBtn = $("vf-demo-btn");
  if (demoBtn) demoBtn.addEventListener("click", async () => { const r = await post("/verify/demo-confirm"); if (r.ok) location.href = r.data.next || "/"; });

  /* resume: someone who already submitted comes back to the page */
  if (root.dataset.status === "pending" && root.dataset.blocked !== "1") { info("Checking your ID", "We're still checking the ID you sent. This page updates by itself."); show(form, false); startPolling(); }
  else if (root.dataset.status === "retry") { info("Let's try that again", "We couldn't read your ID clearly. Please take a new photo in good light.", true); show(form, false); }
})();
