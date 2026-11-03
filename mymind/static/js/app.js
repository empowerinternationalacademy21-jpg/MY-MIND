/* MyMind core: CSRF-aware fetch, toasts, confirm dialogs, icons, card renderer, reactions, viewer modal, endless scroll, screen-time. */
(function () {
  const csrf = () => document.querySelector('meta[name="csrf"]').content;
  const body = document.body;
  const MM = (window.MyMind = {});
  const NS = "http://www.w3.org/2000/svg";

  MM.api = async function (url, opts = {}) {
    const o = Object.assign({ headers: {} }, opts);
    o.headers["X-CSRFToken"] = csrf();
    if (o.json) { o.method = "POST"; o.headers["Content-Type"] = "application/json"; o.body = JSON.stringify(o.json); }
    let r;
    try { r = await fetch(url, o); } catch (e) { throw new Error("Network problem. Please try again."); }
    let data = {};
    try { data = await r.json(); } catch (e) { }
    if (!r.ok) throw new Error(data.error || "Something went wrong.");
    return data;
  };

  MM.toast = function (msg) {
    const box = document.getElementById("toasts");
    const t = document.createElement("div"); t.className = "toast"; t.textContent = msg; t.setAttribute("role", "status");
    box.appendChild(t); setTimeout(() => t.remove(), 3000);
  };

  /* inline Lucide icon from the page sprite (black line icons) */
  const ic = (name, cls) => {
    const s = document.createElementNS(NS, "svg"); s.setAttribute("class", "ic" + (cls ? " " + cls : "")); s.setAttribute("aria-hidden", "true");
    const u = document.createElementNS(NS, "use"); u.setAttribute("href", "#i-" + name); s.appendChild(u); return s;
  };
  MM.icon = ic;
  const el = (tag, cls, text) => { const n = document.createElement(tag); if (cls) n.className = cls; if (text != null) n.textContent = text; return n; };
  MM.el = el;
  const fmt = (s) => { if (!s) return ""; const m = Math.floor(s / 60), r = s % 60; return m + ":" + String(r).padStart(2, "0"); };

  /* ---------- embedded players ----------
     Builds the official YouTube / Spotify iframe. Playback only ever starts after the child/caregiver tapped
     something (the card, the play button), so autoplay=1 here is the result of an explicit tap, never automatic. */
  MM.embedSrc = function (item) {
    if (!item.embed) return "";
    if (item.provider === "youtube") return item.embed + (item.embed.includes("?") ? "&" : "?") + "autoplay=1&playsinline=1";
    return item.embed;
  };
  MM.player = function (item) {
    const spotify = item.provider === "spotify";             // YouTube songs are music videos: they need the video size
    const f = el("iframe", spotify ? "spot" : "");
    f.src = MM.embedSrc(item);
    f.title = item.title;
    f.allow = "autoplay; encrypted-media; picture-in-picture; fullscreen; clipboard-write";
    f.referrerPolicy = "strict-origin-when-cross-origin";   // YouTube refuses embeds that send no referrer
    f.setAttribute("allowfullscreen", "");
    if (!spotify) {                                          // videos need an explicit size, a bare iframe is only 300x150
      f.style.width = "100%"; f.style.aspectRatio = item.type === "short" ? "9 / 16" : "16 / 9";
      f.style.maxHeight = "70vh"; f.style.border = "0"; f.style.borderRadius = "12px"; f.style.background = "#000";
    }
    return f;
  };

  /* ---------- thumbnails never stay blank ----------
     If any picture fails to load (expired link, blocked host, offline), swap in a neutral placeholder so the card
     still shows a picture instead of an empty box. `error` does not bubble, so it is caught in the capture phase. */
  const PLACEHOLDER = "data:image/svg+xml," + encodeURIComponent(
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 160 120"><defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1">' +
    '<stop offset="0" stop-color="#cfe5ff"/><stop offset="1" stop-color="#e1d6fb"/></linearGradient></defs>' +
    '<rect width="160" height="120" fill="url(#g)"/><circle cx="80" cy="60" r="24" fill="#fff" opacity=".9"/>' +
    '<path d="M72 48l22 12-22 12z" fill="#1f78f0"/></svg>');
  MM.placeholder = PLACEHOLDER;
  document.addEventListener("error", (e) => {
    const t = e.target;
    if (!(t instanceof HTMLImageElement) || t.dataset.fb) return;
    t.dataset.fb = "1";
    t.src = PLACEHOLDER;
  }, true);

  /* confirmation dialogs for forms/buttons with data-confirm */
  document.addEventListener("submit", (e) => {
    const f = e.target; const msg = f.dataset.confirm || (e.submitter && e.submitter.dataset.confirm);
    if (!msg || f.dataset.ok) return;
    e.preventDefault();
    const dlg = document.getElementById("confirm-dlg");
    dlg.querySelector("p").textContent = msg; dlg.showModal();
    dlg.querySelector("[data-yes]").onclick = () => { dlg.close(); f.dataset.ok = "1"; f.requestSubmit(e.submitter); };
    dlg.querySelector("[data-no]").onclick = () => dlg.close();
  });
  document.addEventListener("click", (e) => {
    if (e.target.closest("[data-close]")) e.target.closest("dialog").close();
    const eye = e.target.closest("[data-toggle-pw]");
    if (eye) {
      const input = eye.parentElement.querySelector("input"); const show = input.type === "password";
      input.type = show ? "text" : "password"; eye.replaceChildren(ic(show ? "eye-off" : "eye")); eye.setAttribute("aria-label", show ? "Hide password" : "Show password");
    }
  });

  MM.react = async function (item, type) {
    try { await MM.api("/api/react", { json: { content_id: item.id, type } }); } catch (e) { MM.toast(e.message); }
  };

  /* ---------- action buttons ---------- */
  const mkBtn = (cls, icon, label, pressed) => {
    const b = el("button", cls); b.type = "button"; b.setAttribute("aria-label", label); b.title = label; b.dataset.label = label; b.appendChild(ic(icon));
    if (pressed !== undefined) b.setAttribute("aria-pressed", pressed ? "true" : "false"); return b;
  };
  MM.favButton = function (item, cls) {
    const fav = mkBtn(cls || "fav", "heart", "Favorite", item.favorite);
    fav.onclick = async (e) => { e.stopPropagation(); try { const r = await MM.api("/api/favorite", { json: { content_id: item.id } }); fav.setAttribute("aria-pressed", r.favorite); MM.toast(r.favorite ? "Added to favorites" : "Removed from favorites"); } catch (err) { MM.toast(err.message); } };
    return fav;
  };
  MM.tools = function (item, card, opts = {}) {
    const wrap = el("div", "tools");
    const like = mkBtn("tool", "thumbs-up", "I like this", item.reaction === "like");
    const dislike = mkBtn("tool dis", "thumbs-down", "Not for me", item.reaction === "dislike");
    like.onclick = async () => { await MM.react(item, "like"); like.setAttribute("aria-pressed", "true"); dislike.setAttribute("aria-pressed", "false"); MM.toast("Nice choice!"); };
    dislike.onclick = async () => { await MM.react(item, "dislike"); dislike.setAttribute("aria-pressed", "true"); like.setAttribute("aria-pressed", "false"); MM.toast("Okay, we'll show less like this."); if (opts.hideOnDislike !== false && card) card.style.opacity = ".35"; };
    wrap.append(like, dislike);
    if (opts.withFav) wrap.appendChild(MM.favButton(item, "tool"));
    if (item.type === "video" || item.type === "short") {
      const skip = mkBtn("tool", "skip-forward", "Skip"); skip.onclick = async () => { await MM.react(item, "skip"); if (card) card.style.opacity = ".35"; if (opts.onSkip) opts.onSkip(card); }; wrap.appendChild(skip);
    }
    const more = el("a", "tool"); more.href = "/explore/" + item.id; more.title = "More like this"; more.setAttribute("aria-label", "More like this"); more.dataset.label = "More like this";
    more.appendChild(ic("search")); more.addEventListener("click", () => MM.react(item, "explore")); wrap.appendChild(more);
    return wrap;
  };

  /* ---------- cards ---------- */
  const attribution = (item) => {
    if (item.provider !== "pexels" || !item.attribution.photographer) return null;
    const p = el("p", "tile__meta"); p.append("Photo by ");
    const a = el("a", null, item.attribution.photographer); a.href = item.attribution.photographer_url; a.target = "_blank"; a.rel = "noopener noreferrer"; p.append(a, " on ");
    const a2 = el("a", null, "Pexels"); a2.href = "https://www.pexels.com"; a2.target = "_blank"; a2.rel = "noopener noreferrer"; p.append(a2); return p;
  };
  MM.card = function (item, opts = {}) {
    if (item.type === "song") return MM.songRow(item, opts);
    const card = el("article", "tile tile--" + item.type);
    const media = el("button", "tile__media"); media.type = "button"; media.setAttribute("aria-label", "Open " + item.title);
    if (item.thumb) { const img = el("img"); img.src = item.thumb; img.alt = ""; img.loading = "lazy"; media.appendChild(img); }
    media.addEventListener("click", () => MM.open(item));
    card.append(media, MM.favButton(item));
    if (item.type !== "picture") {
      const k = el("span", "kind"); k.appendChild(ic("play", "sm")); media.appendChild(k);
      if (item.attribution.duration) media.appendChild(el("span", "dur", fmt(item.attribution.duration)));
    }
    const b = el("div", "tile__body");
    b.appendChild(el("h3", "tile__title", item.title));
    const meta = el("p", "tile__meta", item.category_label); if (item.demo) { const d = el("span", "badge", "Demo"); d.style.marginLeft = ".35rem"; meta.appendChild(d); }
    b.appendChild(meta); const at = attribution(item); if (at) b.appendChild(at);
    b.appendChild(MM.tools(item, card, opts)); card.appendChild(b);
    return card;
  };
  MM.songRow = function (item, opts = {}) {
    const row = el("article", "song rows-item");
    const art = el("button", "art"); art.type = "button"; art.setAttribute("aria-label", "Open " + item.title);
    if (item.thumb) { const img = el("img"); img.src = item.thumb; img.alt = ""; img.loading = "lazy"; art.appendChild(img); }
    art.onclick = () => MM.open(item);
    const g = el("div", "grow"); g.append(el("p", "t", item.title));
    const sub = el("p", "s", (item.attribution.artist || item.category_label)); if (item.demo) { const d = el("span", "badge", "Demo"); d.style.marginLeft = ".35rem"; sub.appendChild(d); } g.appendChild(sub);
    g.appendChild(MM.tools(item, row, opts));
    const d = el("span", "d", fmt(item.attribution.duration));
    const play = el("button", "play"); play.type = "button"; play.setAttribute("aria-label", "Play " + item.title); play.appendChild(ic("play")); play.onclick = () => MM.open(item);
    row.append(art, g, d, MM.favButton(item, "tool"), play);
    return row;
  };

  /* ---------- viewer modal (picture / YouTube embed / Spotify embed) ---------- */
  MM.open = function (item) {
    const dlg = document.getElementById("viewer"); const box = dlg.querySelector(".dlg-body");
    box.replaceChildren(); MM.react(item, "selected");
    box.appendChild(el("h2", null, item.title));
    const opened = Date.now();
    if (item.type === "picture") { const img = el("img", "big"); img.src = item.thumb; img.alt = item.title; box.appendChild(img); const at = attribution(item); if (at) box.appendChild(at); }
    else if (item.embed) {
      box.appendChild(MM.player(item));
      if (item.provider === "youtube") box.appendChild(el("p", "tile__meta", "If the video does not start, use “Watch on YouTube” below."));
    } else {
      const n = el("p", "notice"); n.append(ic("info"), el("span", null, "This is demo content, so there is nothing to play. Add API keys to see real videos and music.")); box.appendChild(n);
      if (item.thumb) { const img = el("img", "big"); img.src = item.thumb; img.alt = ""; box.appendChild(img); }
    }
    if (item.url && item.provider !== "demo") {
      const a = el("a", "btn small", item.provider === "spotify" ? "Open in Spotify" : item.provider === "youtube" ? "Watch on YouTube" : "View original");
      a.href = item.url; a.target = "_blank"; a.rel = "noopener noreferrer"; box.appendChild(a);
    }
    box.appendChild(MM.tools(item, null, { hideOnDislike: false, withFav: true }));
    dlg.showModal();
    dlg.onclose = () => { box.replaceChildren(); if (item.embed && Date.now() - opened > 10000) MM.react(item, "watched"); };
  };

  /* ---------- grid helpers ---------- */
  MM.skeletons = (n = 6) => { const f = document.createDocumentFragment(); for (let i = 0; i < n; i++) f.appendChild(el("div", "skeleton")); return f; };
  MM.renderItems = function (grid, items, opts) {
    if (!items.length) { grid.replaceChildren(el("div", "empty", "Nothing here yet. Try another topic.")); return; }
    grid.replaceChildren(...items.map((i) => MM.card(i, opts)));
  };
  MM.notice = function (host, text) {
    const old = host.querySelector(".notice"); if (old) old.remove();
    if (text) { const n = el("p", "notice"); n.append(ic("info"), el("span", null, text)); host.prepend(n); }
  };

  /* ---------- endless scrolling ----------
     Calls load() whenever `target` comes within 700px of the viewport, and once more right after each load
     (in case the page is still not full). Returns { check } so callers can re-test manually. */
  MM.endless = function (target, load) {
    let queued = false;
    const check = () => {
      if (queued || !target.isConnected) return;
      const r = target.getBoundingClientRect();
      if (r.top < window.innerHeight + 700 && r.bottom > -700) { queued = true; Promise.resolve(load()).finally(() => { queued = false; }); }
    };
    if ("IntersectionObserver" in window) {
      new IntersectionObserver((es) => { if (es.some((e) => e.isIntersecting)) check(); }, { rootMargin: "700px 0px" }).observe(target);
    } else { window.addEventListener("scroll", check, { passive: true }); }
    return { check };
  };

  MM.browse = function (cfg) {
    const grid = document.getElementById("grid"); const q = document.getElementById("q"); const form = document.getElementById("search");
    const chips = document.querySelectorAll(".chip[data-cat]"); const more = document.getElementById("more");
    const sentinel = more || grid.insertAdjacentElement("afterend", el("div", "sentinel"));
    let cat = "", page = 1, loading = false, done = false, gen = 0; const seen = new Set();

    async function load(append, tries = 0) {
      if (append && (loading || done)) return;
      const my = append ? gen : ++gen;              // a new search/category supersedes any request still in flight
      loading = true;
      if (!append) { grid.replaceChildren(MM.skeletons()); page = 1; done = false; seen.clear(); if (more) more.hidden = false; }
      const params = new URLSearchParams({ page });
      if (cat) params.set("category", cat); if (q && q.value.trim()) params.set("q", q.value.trim());
      try {
        const d = await MM.api(cfg.endpoint + "?" + params);
        if (my !== gen) return;
        MM.notice(grid.parentElement, d.notice);
        const fresh = d.items.filter((i) => !seen.has(i.id)); fresh.forEach((i) => seen.add(i.id));
        if (append) fresh.forEach((i) => grid.appendChild(MM.card(i, cfg.card))); else MM.renderItems(grid, fresh, cfg.card);
        if (!d.items.length || d.more === false) done = true;
        else if (!fresh.length && tries < 3) { page++; loading = false; return load(true, tries + 1); }   // all repeats: try the next page
      } catch (e) {
        if (my !== gen) return;
        if (append) { page = Math.max(1, page - 1); MM.toast(e.message); } else grid.replaceChildren(el("div", "empty", e.message));
        loading = false; return;                    // no auto-retry loop after an error; the "more" button still works
      }
      loading = false;
      if (more) more.hidden = done;
      if (!done) setTimeout(endless.check, 50);     // page not full yet? keep filling
    }
    const next = () => { page++; return load(true); };
    const endless = MM.endless(sentinel, next);

    chips.forEach((c) => c.addEventListener("click", () => { chips.forEach((x) => x.setAttribute("aria-pressed", "false")); c.setAttribute("aria-pressed", "true"); cat = c.dataset.cat; load(false); }));
    if (form) form.addEventListener("submit", (e) => { e.preventDefault(); load(false); });
    if (more) more.addEventListener("click", next);
    load(false);
  };

  /* ---------- gentle screen-time reminder (caregiver-set; counted in this browser only) ---------- */
  (function () {
    const mins = parseInt(body.dataset.screen || "0", 10); if (!mins || body.dataset.app !== "1") return;
    const key = "mm_time_" + new Date().toISOString().slice(0, 10);
    let used = parseInt(localStorage.getItem(key) || "0", 10), limit = mins * 60;
    setInterval(() => { if (document.hidden) return; used++; localStorage.setItem(key, used); if (used === limit) { const d = document.getElementById("break-dlg"); if (d && !d.open) d.showModal(); } }, 1000);
    const ext = document.getElementById("break-more");
    if (ext) ext.onclick = () => { limit = used + 600; document.getElementById("break-dlg").close(); };
  })();

  /* ---------- optional spoken labels (off by default) ---------- */
  if (body.dataset.speak === "1" && "speechSynthesis" in window) {
    document.addEventListener("focusin", (e) => { const t = e.target.closest("[data-label],[aria-label]"); if (!t) return; speechSynthesis.cancel(); speechSynthesis.speak(new SpeechSynthesisUtterance(t.dataset.label || t.getAttribute("aria-label"))); });
  }
})();