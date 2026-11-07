(function () {
  const MM = window.MyMind;
  const $ = (id) => document.getElementById(id);
  const root = $("sh"), top = $("top"), grid = $("grid"), more = $("more"), emptyBox = $("empty"),
    secTop = $("sec-top"), secMore = $("sec-more"), viewAll = $("viewall");
  if (!MM || !root) return;
  const chips = document.querySelectorAll(".sh-chip[data-cat]");
  const HERO = 5;                                  // first 5 shorts go in the "Top shorts today" carousel
  const AUTOPLAY = true;                           // the short on screen plays by itself; set to false to require a tap
  const form = $("sh-search"), qInput = $("sh-q"), clearBtn = $("sh-clear"), topHead = $("top-h"), moreHead = $("more-h");
  const MIN_CHARS = 2;
  let cat = "", q = "", page = 1, loading = false, done = false, gen = 0;
  let nearEnd = null;                              // page-level observer: loads more while browsing the cards
  const seen = new Set(), items = [], cards = new Map();

  // viewer state (the viewer is an endless, vertically snapping feed of full-screen slides)
  let dlg = null, feed = null, count = null, activeObs = null, idx = 0, lastActivityIdx = -1, built = false, playTimer = null;
  const states = new Map();                        // item id -> { item, el, stage, playing, timer }

  /* ---------- small helpers ---------- */
  const NS = "http://www.w3.org/2000/svg";
  function glyph(paths) {                          // tiny inline line icons (Lucide, ISC licence)
    const s = document.createElementNS(NS, "svg");
    s.setAttribute("class", "ic"); s.setAttribute("viewBox", "0 0 24 24"); s.setAttribute("aria-hidden", "true");
    paths.forEach((d) => { const p = document.createElementNS(NS, "path"); p.setAttribute("d", d); s.appendChild(p); });
    return s;
  }
  const CHEV_LEFT = ["m15 18-6-6 6-6"], CHEV_UP = ["m18 15-6-6-6 6"], CHEV_DOWN = ["m6 9 6 6 6-6"];
  const channelOf = (item) => (item.attribution && item.attribution.channel) || item.category_label || "MyMind";
  function avatar(name) { return MM.el("span", "sh-av", (name || "M").trim().charAt(0).toUpperCase()); }
  const act = (fn) => async () => { try { await fn(); } catch (e) { MM.toast((e && e.message) || "Something went wrong."); } };
  const scrollBehavior = () =>
    (window.matchMedia("(prefers-reduced-motion: reduce)").matches || document.body.classList.contains("reduced-motion")) ? "auto" : "smooth";

  /* ---------- cards (image on top, text underneath, normal flow) ---------- */
  function card(item) {
    const b = MM.el("button", "sh-card"); b.type = "button"; b.setAttribute("aria-label", "Watch " + item.title);
    const th = MM.el("span", "sh-thumb");
    if (item.thumb) { const i = MM.el("img"); i.src = item.thumb; i.alt = ""; i.loading = "lazy"; i.decoding = "async"; th.appendChild(i); }
    if (item.category_label) th.appendChild(MM.el("span", "sh-tag", item.category_label));
    if (item.demo) th.appendChild(MM.el("span", "sh-demo", "Demo"));
    const pl = MM.el("span", "sh-play"); pl.appendChild(MM.icon("play")); th.appendChild(pl);
    const body = MM.el("span", "sh-body");
    const by = MM.el("span", "sh-by"); const ch = channelOf(item);
    by.append(avatar(ch), MM.el("span", "sh-by-name", ch));
    body.append(by, MM.el("span", "sh-title", item.title));
    b.append(th, body);
    b.addEventListener("click", () => openAt(items.indexOf(item)));
    cards.set(item.id, b);
    return b;
  }
  function placeholder() {
    const c = MM.el("div", "sh-card sh-sk"); c.setAttribute("aria-hidden", "true");
    c.append(MM.el("span", "sh-thumb"), MM.el("span", "sk-line"), MM.el("span", "sk-line s"));
    c.children[1].style.margin = ".75rem .4rem 0"; c.children[2].style.margin = ".5rem .4rem .4rem";
    return c;
  }
  function sync() {                                // show or hide sections depending on what is loaded
    secTop.hidden = top.children.length === 0;
    secMore.hidden = grid.children.length === 0;
  }
  function showEmpty(msg) {
    top.replaceChildren(); grid.replaceChildren(); secTop.hidden = true; secMore.hidden = true;
    emptyBox.textContent = msg; emptyBox.hidden = false;
  }

  /* ---------- endless loading (page) ---------- */
  function watchEnd() {
    if (nearEnd) nearEnd.disconnect();
    const all = Array.from(top.children).concat(Array.from(grid.children));
    if (!all.length || done) return;
    if (!("IntersectionObserver" in window)) return;               // "Show more" button still works
    const target = all[Math.max(0, all.length - 3)];
    nearEnd = new IntersectionObserver((es) => { if (es.some((e) => e.isIntersecting)) next(); }, { rootMargin: "400px 0px" });
    nearEnd.observe(target);
  }

  async function load(append, tries = 0) {
    if (append && (loading || done)) return;
    const my = append ? gen : ++gen;
    loading = true;
    if (!append) {
      page = 1; done = false; seen.clear(); items.length = 0; cards.clear();
      resetFeed();
      emptyBox.hidden = true; secTop.hidden = false; secMore.hidden = false; more.hidden = false;
      top.replaceChildren(placeholder(), placeholder(), placeholder());
      grid.replaceChildren(placeholder(), placeholder());
    }
    const params = new URLSearchParams({ page }); if (cat) params.set("category", cat); if (q) params.set("q", q);
    try {
      const d = await MM.api("/api/shots?" + params);
      if (my !== gen) return;
      MM.notice(root, d.notice);
      const fresh = d.items.filter((i) => !seen.has(i.id)); fresh.forEach((i) => seen.add(i.id));
      if (!append) { top.replaceChildren(); grid.replaceChildren(); }
      fresh.forEach((i) => {
        items.push(i);
        (items.length <= HERO ? top : grid).appendChild(card(i));
        if (built) addSlide(i);                                    // viewer feed grows as more shorts arrive
      });
      if (!d.items.length || d.more === false) done = true;
      else if (!fresh.length && tries < 3) { page++; loading = false; return load(true, tries + 1); }
      if (!items.length) showEmpty(q ? "No shorts found for \u201c" + q + "\u201d. Try another word." : "No short videos found for this topic.");
    } catch (e) {
      if (my !== gen) return;
      if (append) { page = Math.max(1, page - 1); MM.toast(e.message); } else showEmpty(e.message);
      loading = false; return;
    }
    loading = false;
    more.hidden = done;
    sync(); watchEnd(); updateCount();
  }
  const next = () => { page++; return load(true); };

  /* ---------- viewer: endless vertical feed ---------- */
  function updateCount() { if (count) count.textContent = items.length ? (idx + 1) + " / " + items.length + (done ? "" : "+") : ""; }

  function ensureViewer() {
    if (dlg) return;
    dlg = MM.el("dialog", "sv"); dlg.setAttribute("aria-label", "Short videos");
    const tb = MM.el("div", "sv-top");
    const mk = (paths, label, fn) => {
      const b = MM.el("button", "sv-ic"); b.type = "button"; b.setAttribute("aria-label", label); b.title = label;
      b.appendChild(glyph(paths)); b.onclick = fn; return b;
    };
    const nav = MM.el("div", "sv-nav");
    nav.append(mk(CHEV_UP, "Previous short", () => go(-1)), mk(CHEV_DOWN, "Next short", () => go(1)));
    count = MM.el("span", "sv-count");
    tb.append(mk(CHEV_LEFT, "Close", () => dlg.close()), count, nav);

    feed = MM.el("div", "sv-feed"); feed.tabIndex = -1;
    dlg.append(tb, feed);
    dlg.addEventListener("close", () => { stopAll(); });           // stops any playing video
    dlg.addEventListener("keydown", (e) => {
      if (e.key === "ArrowDown" || e.key === "ArrowRight") { e.preventDefault(); go(1); }
      else if (e.key === "ArrowUp" || e.key === "ArrowLeft") { e.preventDefault(); go(-1); }
    });
    document.body.appendChild(dlg);

    if ("IntersectionObserver" in window) {
      // active slide = the one that is at least 60% visible; slides scrolled fully away go back to their poster
      activeObs = new IntersectionObserver((entries) => {
        entries.forEach((en) => {
          if (en.isIntersecting && en.intersectionRatio >= 0.6) setActive(en.target);
          else if (!en.isIntersecting) resetMedia(en.target.dataset.id);
        });
      }, { root: feed, threshold: [0, 0.6] });
    }
  }

  function setActive(el) {
    const i = Array.prototype.indexOf.call(feed.children, el);
    if (i < 0) return;
    if (lastActivityIdx >= 0 && i > lastActivityIdx) MM.activity.log("next", null, items[lastActivityIdx]);
    lastActivityIdx = i;
    idx = i; updateCount();
    const st = states.get(el.dataset.id);
    states.forEach((other, id) => { if (other !== st) resetMedia(id); });   // pause every short that is not on screen
    if (AUTOPLAY && st) scheduleAutoplay(st);                      // and play the one that is
    if (!done && !loading && idx >= items.length - 3) next();      // endless scrolling: fetch the next page early
  }

  function go(n) {
    const t = feed && feed.children[idx + n];
    if (t) t.scrollIntoView({ block: "start", behavior: scrollBehavior() });
    else if (n > 0) endOfFeed();
  }
  function endOfFeed() {
    if (!done) { next(); MM.toast("Loading more shorts…"); } else MM.toast("That's all the shorts for now.");
  }

  function mediaFor(st) {                                          // poster + play; playback only on an explicit tap
    const item = st.item;
    const media = MM.el("div", "sv-media");
    if (item.thumb) { const i = MM.el("img"); i.src = item.thumb; i.alt = ""; i.loading = "lazy"; media.appendChild(i); }
    if (item.demo) media.appendChild(MM.el("span", "sh-demo", "Demo"));
    const pb = MM.el("button", "sv-play"); pb.type = "button"; pb.setAttribute("aria-label", "Play " + item.title);
    pb.appendChild(MM.icon("play", "lg"));
    pb.onclick = () => startPlayback(st, true);                    // manual tap (also the fallback if autoplay is blocked)
    st.media = media;
    media.appendChild(pb);
    return media;
  }
  function embedFrame(item) {
    const f = MM.player(item);                                      // official embed with referrer policy + allow list
    try {
      const u = new URL(f.src, location.href);
      u.searchParams.set("autoplay", "1"); u.searchParams.set("playsinline", "1");
      const m = u.pathname.match(/\/embed\/([^/?]+)/);
      if (m) { u.searchParams.set("loop", "1"); u.searchParams.set("playlist", m[1]); }   // loops like a Short
      f.src = u.toString();
    } catch (e) { /* keep the original src */ }
    const allow = f.getAttribute("allow") || "";
    if (!/autoplay/.test(allow)) f.setAttribute("allow", (allow ? allow + "; " : "") + "autoplay; encrypted-media; picture-in-picture; fullscreen");
    Object.assign(f.style, { maxHeight: "none", height: "100%", width: "100%", aspectRatio: "auto", borderRadius: "0", display: "block" });
    return f;
  }
  function startPlayback(st, explicit) {
    const item = st.item;
    if (st.playing) return;
    if (!item.embed) { if (explicit) MM.toast("Demo content has nothing to play."); return; }
    if (explicit) MM.react(item, "selected");                       // only a deliberate tap counts as a choice, autoplay does not
    st.media.replaceChildren(embedFrame(item));
    st.playing = true; clearTimeout(st.timer);
    MM.activity.startWatch(item);
    st.timer = setTimeout(() => MM.react(item, "watched"), 10000);  // "watched" = still on this short after 10 s
  }
  function scheduleAutoplay(st) {                                   // short delay so fast flicks do not start every video
    clearTimeout(playTimer);
    playTimer = setTimeout(() => {
      if (!dlg || !dlg.open || document.hidden) return;
      if (feed.children[idx] !== st.el) return;                     // the user already moved on
      startPlayback(st, false);
    }, 250);
  }
  function resetMedia(id) {
    const st = states.get(id);
    if (st && st.playing) {
      clearTimeout(st.timer); st.playing = false;
      MM.activity.endWatch();
      st.stage.replaceChildren(mediaFor(st));
    }
  }
  function stopAll() { clearTimeout(playTimer); states.forEach((st, id) => resetMedia(id)); }

  function btn(iconNode, label, fn, pressed) {
    const b = MM.el("button"); b.type = "button"; b.setAttribute("aria-label", label); b.title = label;
    b.appendChild(iconNode);
    if (pressed !== undefined) b.setAttribute("aria-pressed", pressed ? "true" : "false");
    b.onclick = fn; return b;
  }

  function addSlide(item) {
    const el = MM.el("article", "sv-slide"); el.dataset.id = item.id;
    const stage = MM.el("div", "sv-stage"), info = MM.el("div", "sv-info"), bar = MM.el("div", "sv-bar");
    const st = { item, el, stage, playing: false, timer: null };
    stage.appendChild(mediaFor(st));

    const ch = channelOf(item);
    const chip = MM.el("span", "sv-chip"); chip.append(avatar(ch), MM.el("span", null, ch));
    const meta = MM.el("div", "sv-metarow"); meta.appendChild(chip);
    if (item.category_label) meta.appendChild(MM.el("span", "sv-cat", item.category_label));
    info.append(meta, MM.el("h2", "sv-title", item.title));

    const like = btn(MM.icon("thumbs-up"), "I like this", act(async () => {
      await MM.react(item, "like"); item.reaction = "like"; like.setAttribute("aria-pressed", "true"); MM.toast("Nice choice!");
    }), item.reaction === "like");
    const fav = MM.favButton(item, "fav");
    const dis = btn(MM.icon("thumbs-down"), "Not for me", act(async () => {
      await MM.react(item, "dislike"); el.classList.add("is-dim");
      const c = cards.get(item.id); if (c) c.classList.add("is-dim");
      MM.toast("Okay, we'll show less like this.");
    }));
    const exp = MM.el("a"); exp.href = "/explore/" + item.id; exp.setAttribute("aria-label", "More like this"); exp.title = "More like this";
    exp.appendChild(MM.icon("search")); exp.onclick = () => MM.react(item, "explore");
    const skip = btn(MM.icon("skip-forward"), "Skip", act(async () => {
      await MM.react(item, "skip");
      const n = el.nextElementSibling;
      if (n) n.scrollIntoView({ block: "start", behavior: scrollBehavior() }); else endOfFeed();
    }));
    bar.append(like, fav, dis, exp, skip);

    el.append(stage, info, bar);
    feed.appendChild(el);
    states.set(item.id, st);
    if (activeObs) activeObs.observe(el);
  }

  function resetFeed() {                                           // topic changed: drop the old feed
    stopAll();
    if (activeObs) activeObs.disconnect();
    states.clear(); built = false; idx = 0;
    if (feed) feed.replaceChildren();
    updateCount();
  }

  function openAt(i) {
    if (i < 0 || !items[i]) return;
    ensureViewer();
    if (!built) {                                                  // build every short loaded so far, once
      items.forEach(addSlide); built = true;
    }
    if (typeof dlg.showModal === "function") dlg.showModal(); else dlg.setAttribute("open", "");
    idx = i; lastActivityIdx = i; updateCount();
    const jump = () => { const s = feed.children[i]; if (s) feed.scrollTop = s.offsetTop; };
    jump(); requestAnimationFrame(jump);                           // land exactly on the tapped short
    const st0 = states.get(items[i].id); if (AUTOPLAY && st0) scheduleAutoplay(st0);
    const first = dlg.querySelector(".sv-ic"); if (first) first.focus();
  }

  /* ---------- search ---------- */
  function setHeadings() {                         // section titles follow the mode: search results or the normal feed
    if (topHead) topHead.textContent = q ? "Results for \u201c" + q + "\u201d" : "Top shorts today";
    if (moreHead) moreHead.textContent = q ? "More results" : "More shorts";
    if (clearBtn) clearBtn.hidden = !(qInput && qInput.value);
  }
  function selectChip(value) {
    chips.forEach((x) => x.setAttribute("aria-pressed", x.dataset.cat === value ? "true" : "false"));
  }
  function runSearch() {
    const v = (qInput.value || "").trim().slice(0, 60);
    if (v && v.length < MIN_CHARS) { MM.toast("Type at least " + MIN_CHARS + " letters to search."); return; }
    if (v === q) return;                           // nothing changed: do not spend another search
    q = v; cat = ""; selectChip("");
    if (q && MM.activity) MM.activity.log("search");
    setHeadings(); load(false);
  }
  function clearSearch() {
    qInput.value = "";
    if (q) { q = ""; setHeadings(); load(false); } else setHeadings();
    qInput.focus();
  }
  if (form && qInput) {
    form.addEventListener("submit", (e) => { e.preventDefault(); runSearch(); });   // searches on Enter / button only (saves API quota)
    qInput.addEventListener("input", () => { if (clearBtn) clearBtn.hidden = !qInput.value; });
    qInput.addEventListener("keydown", (e) => { if (e.key === "Escape" && qInput.value) { e.preventDefault(); clearSearch(); } });
    if (clearBtn) clearBtn.addEventListener("click", clearSearch);
    const initial = (new URLSearchParams(location.search).get("q") || "").trim().slice(0, 60);   // e.g. from the global search
    if (initial.length >= MIN_CHARS) { qInput.value = initial; q = initial; }
    setHeadings();
  }

  /* ---------- wiring ---------- */
  chips.forEach((c) => c.addEventListener("click", () => {
    selectChip(c.dataset.cat); cat = c.dataset.cat;
    if (q) { q = ""; if (qInput) qInput.value = ""; setHeadings(); }   // picking a topic leaves search mode
    load(false);
  }));
  document.addEventListener("visibilitychange", () => {            // pause when the tab/app is hidden, resume when back
    if (!dlg || !dlg.open) return;
    if (document.hidden) { stopAll(); return; }
    const el = feed.children[idx], st = el && states.get(el.dataset.id);
    if (AUTOPLAY && st) scheduleAutoplay(st);
  });
  if (more) more.addEventListener("click", next);
  if (viewAll) viewAll.addEventListener("click", () => openAt(0));
  load(false);
})();
