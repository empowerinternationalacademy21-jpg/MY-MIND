/* My World UI: the map (3D scene or flat SVG fallback), place labels, stop sheet (friends, shelves), caregiver controls.
   Data comes from /api/world (embedded in the page first). Everything the caregiver can change is saved server-side. */
(function () {
  "use strict";
  var root = document.getElementById("world3d");
  if (!root || !window.MyMind) return;
  var MM = window.MyMind, NS = window.MMWorld || {}, el = MM.el, ic = MM.icon;
  var preview = root.dataset.mode === "preview", apiRoot = root.dataset.apiRoot || "/api/world";
  var qs = new URLSearchParams(location.search);
  var $ = function (id) { return document.getElementById(id); };
  var viewport = $("w3d-viewport"), labelsLayer = $("w3d-labels"), toolbar = $("w3d-toolbar"), listEl = $("w3d-list"), sheet = $("w3d-sheet"),
      gear = $("w3d-gear"), themeEl = $("w3d-theme"), loading = $("w3d-loading"), stage = $("w3d-stage");
  var data = JSON.parse($("world-data").textContent);
  var mode = "3d", scene = null, labelEls = {}, openKey = null, timers = [], lastFocus = null;
  var osReduced = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  var STOPS = function () { var m = {}; data.stops.forEach(function (s) { m[s.key] = s; }); return m; };

  // ------------------------------------------------------------------ helpers
  function store(k, v) { try { if (v === undefined) return localStorage.getItem(k); localStorage.setItem(k, v); } catch (e) { return null; } }
  function animationOn() { return data.settings.animation && !data.reduced_motion && !osReduced; }
  function probeGL() {
    try {
      var c = document.createElement("canvas"), gl = c.getContext("webgl2") || c.getContext("webgl");
      if (!gl) return null;
      var ext = gl.getExtension("WEBGL_debug_renderer_info"), r = ext ? String(gl.getParameter(ext.UNMASKED_RENDERER_WEBGL)) : "";
      var lose = gl.getExtension("WEBGL_lose_context"); if (lose) lose.loseContext();
      return { renderer: r, software: /swiftshader|llvmpipe|softpipe|software|basic render/i.test(r) };
    } catch (e) { return null; }
  }
  function decideMode() {
    if (qs.get("flat") === "1" || store("mm-world-flat") === "1") return "flat";
    if (!NS.createScene || !window.MM3D) return "flat";
    var info = probeGL();
    if (!info) return "flat";
    if (info.software && qs.get("gl") !== "force") return "flat";            // a software renderer would be slow: the simple map is kinder
    return "3d";
  }
  function hash(s) { var h = 0; for (var i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) >>> 0; return h; }
  function slotIndex(key, n, secs) { return n ? (Math.floor(Date.now() / (secs * 1000)) + hash(key)) % n : 0; }   // stable across refreshes, changes every `secs`
  var audio = null;
  function tick() {
    if (!data.settings.sound || data.reduced_motion) return;
    try {
      audio = audio || new (window.AudioContext || window.webkitAudioContext)();
      var t = audio.currentTime, o = audio.createOscillator(), g = audio.createGain();
      o.type = "sine"; o.frequency.setValueAtTime(587, t); o.frequency.setValueAtTime(784, t + 0.07);
      g.gain.setValueAtTime(0.0001, t); g.gain.exponentialRampToValueAtTime(0.05, t + 0.02); g.gain.exponentialRampToValueAtTime(0.0001, t + 0.2);
      o.connect(g); g.connect(audio.destination); o.start(t); o.stop(t + 0.22);
    } catch (e) {}
  }
  function clearTimers() { timers.forEach(clearInterval); timers = []; }
  function btn(cls, label, icon, onClick, aria) {
    var b = el("button", cls); b.type = "button";
    if (icon) b.appendChild(ic(icon));
    if (label) b.appendChild(el("span", null, label));
    if (aria) b.setAttribute("aria-label", aria);
    b.addEventListener("click", onClick); return b;
  }

  // ------------------------------------------------------------------ mount / unmount
  function unmount() {
    clearTimers(); if (scene) { scene.dispose(); scene = null; }
    viewport.replaceChildren(); labelsLayer.replaceChildren(); labelEls = {}; viewport.removeAttribute("style");
  }
  function mount() {
    unmount();
    renderTheme(); renderList(); renderToolbar();
    var s = STOPS();
    if (mode === "3d") {
      try {
        scene = NS.createScene(viewport, data, {
          onPick: function (k) { openStop(k); },
          onLabels: positionLabels,
          onContextLost: function () { fallback("The 3D view stopped, so here is the simple map."); },
          onSlow: function () { offerSimple(); }
        });
        scene.setAnimation(animationOn());
        buildLabels();
      } catch (e) { if (window.console) console.error("world scene failed", e); mode = "flat"; }
    }
    if (mode === "flat") buildFlat();
    loading.hidden = true; stage.classList.toggle("is-flat", mode === "flat"); stage.classList.toggle("is-3d", mode === "3d");
    startRotation(); if (openKey && !s[openKey]) closeSheet(true);
  }
  function fallback(msg) { if (mode === "flat") return; mode = "flat"; if (msg) MM.toast(msg); mount(); }
  function offerSimple() {
    if ($("w3d-slow")) return;
    var n = el("div", "w3d-slow"); n.id = "w3d-slow"; n.setAttribute("role", "status");
    n.append(el("span", null, "The map is running slowly on this device."), btn("btn small", "Use simple map", null, function () { store("mm-world-flat", "1"); fallback(); n.remove(); }), btn("btn small", "Keep 3D", null, function () { n.remove(); }));
    stage.appendChild(n);
  }

  var LEVEL_WORD = ["", "A favourite", "A big favourite", "A top favourite"];
  function renderTheme() {
    var t = data.theme;
    themeEl.replaceChildren(ic(t.icon), el("strong", null, t.label + " world"), el("span", null, " " + t.reason));
    var loves = $("w3d-loves");                                   // interests found from what the child really does (labels only, never numbers)
    if (!loves) return;
    loves.replaceChildren();
    var top = (data.discovery && data.discovery.top) || [];
    if (!top.length) { loves.hidden = true; return; }
    loves.hidden = false; loves.appendChild(el("strong", null, "Lately loved: "));
    top.forEach(function (i) {
      var chip = el("span", "w3d-love"); chip.style.setProperty("--c", i.color); chip.title = LEVEL_WORD[i.level] || "";
      chip.append(ic(i.icon, "sm"), el("span", null, i.label)); loves.appendChild(chip);
    });
  }
  function interestLevel(s) { return s.interest && s.interest.level > 0 ? s.interest.level : 0; }
  function renderList() {
    listEl.replaceChildren();
    data.stops.forEach(function (s) {
      var li = el("li"), b = el("button", "w3d-chip" + (interestLevel(s) ? " has-interest interest-" + interestLevel(s) : "")); b.type = "button"; b.style.setProperty("--c", s.color); b.dataset.key = s.key;
      b.append(ic(s.icon), el("span", null, s.label)); b.addEventListener("click", function () { openStop(s.key, b); });
      if (s.time_label) b.appendChild(el("small", "w3d-time-badge", s.time_label));
      li.appendChild(b); listEl.appendChild(li);
    });
  }
  function renderToolbar() {
    toolbar.replaceChildren();
    if (mode === "3d") {
      toolbar.append(btn("w3d-tool", null, "plus", function () { scene && scene.zoomBy(0.8); }, "Zoom in"), btn("w3d-tool", null, "minus", function () { scene && scene.zoomBy(1.25); }, "Zoom out"),
        btn("w3d-tool", null, "locate-fixed", function () { closeSheet(); scene && scene.reset(); }, "Show the whole map"));
    }
    if (!preview && document.body.dataset.role !== "child") {
      var g = btn("w3d-tool w3d-tool--gear", null, "sliders-horizontal", function () { toggleGear(); }, "World settings (for caregivers)");
      g.id = "w3d-gear-btn"; g.setAttribute("aria-expanded", "false"); g.setAttribute("aria-controls", "w3d-gear"); toolbar.appendChild(g);
    }
  }

  // ------------------------------------------------------------------ 3D labels
  function buildLabels() {
    data.stops.forEach(function (s) {
      var lv = interestLevel(s);
      var b = el("button", "w3d-label" + (lv ? " has-interest interest-" + lv : "")); b.type = "button"; b.dataset.key = s.key; b.style.setProperty("--c", s.color);
      b.setAttribute("aria-label", "Open " + s.label + (lv ? " (" + LEVEL_WORD[lv].toLowerCase() + ")" : ""));
      var bub = el("span", "w3d-bubble");
      if (s.badge) { var im = el("img"); im.src = s.badge; im.alt = ""; bub.appendChild(im); } else bub.appendChild(ic(s.icon));
      if (lv) { var stars = el("span", "w3d-stars"); stars.setAttribute("aria-hidden", "true"); for (var k = 0; k < lv; k++) stars.appendChild(ic("star", "sm")); bub.appendChild(stars); }
      b.append(bub, el("span", "w3d-name", s.label)); if (s.time_label) b.appendChild(el("small", "w3d-time-badge", s.time_label));
      if (s.chars && s.chars.length) { var av = el("img", "w3d-char"); av.alt = ""; av.src = s.chars[slotIndex(s.key, s.chars.length, data.rotation_seconds)]; av.dataset.n = s.chars.length; b.appendChild(av); }
      b.addEventListener("click", function () { openStop(s.key, b); });
      labelsLayer.appendChild(b); labelEls[s.key] = b;
    });
  }
  function positionLabels(list) {
    for (var i = 0; i < list.length; i++) {
      var p = list[i], b = labelEls[p.key]; if (!b) continue;
      b.style.transform = "translate(" + p.x.toFixed(1) + "px," + p.y.toFixed(1) + "px) translate(-50%,-100%) scale(" + p.s.toFixed(2) + ")";
      b.style.visibility = p.visible ? "visible" : "hidden";
    }
  }

  // ------------------------------------------------------------------ flat (simple) map
  var NSVG = "http://www.w3.org/2000/svg";
  function svg(tag, attrs, text) { var n = document.createElementNS(NSVG, tag); for (var k in attrs) n.setAttribute(k, attrs[k]); if (text) n.textContent = text; return n; }
  function buildFlat() {
    var p = data.theme.palette, s = STOPS(), root2 = svg("svg", { viewBox: "-4 0 108 136", class: "w3d-flat", role: "group", "aria-label": "Simple map of your world", preserveAspectRatio: "xMidYMid meet" });
    var defs = svg("defs", {}), lg = svg("linearGradient", { id: "wf-sky", x1: "0", y1: "0", x2: "0", y2: "1" });
    lg.append(svg("stop", { offset: "0", "stop-color": p.sky[0] }), svg("stop", { offset: "1", "stop-color": p.sky[1] }));
    var wg = svg("linearGradient", { id: "wf-sea", x1: "0", y1: "0", x2: "0", y2: "1" }); wg.append(svg("stop", { offset: "0", "stop-color": p.sky[1] }), svg("stop", { offset: "0.25", "stop-color": p.water[1] }), svg("stop", { offset: "1", "stop-color": p.water[0] }));
    defs.append(lg, wg); root2.appendChild(defs);
    root2.append(svg("rect", { x: -200, y: -200, width: 500, height: 520, fill: "url(#wf-sea)" }));
    var fy = function (y) { return (y - 8) * 1.3 + 8; };                       // stretch the map vertically so it fills a portrait screen
    data.bridges.forEach(function (b) { var a = s[b[0]], c = s[b[1]]; if (a && c) root2.appendChild(svg("line", { x1: a.x, y1: fy(a.y), x2: c.x, y2: fy(c.y), stroke: "#c9955a", "stroke-width": 1.6, "stroke-dasharray": "1.2 1", "stroke-linecap": "round" })); });
    data.stops.forEach(function (st) {
      var g = svg("g", { class: "flat-stop", tabindex: 0, role: "button", "aria-label": "Open " + st.label, transform: "translate(" + st.x + " " + fy(st.y) + ")" });
      var lvl = interestLevel(st);
      if (lvl) g.append(svg("circle", { r: 9.2 + lvl * 1.1, fill: "none", stroke: st.color, "stroke-width": 0.9 + lvl * 0.3, opacity: 0.55, class: "flat-halo" }));
      g.append(svg("circle", { r: 8.2, fill: p.sand }), svg("circle", { r: 7.2, fill: p.grass }), svg("circle", { r: 5.4, fill: st.color }));
      var u = svg("g", { stroke: "#fff", fill: "none", "stroke-width": 2.1, "stroke-linecap": "round", "stroke-linejoin": "round" }), use = svg("use", { href: "#i-" + st.icon, x: -3.2, y: -3.2, width: 6.4, height: 6.4 });
      u.appendChild(use); g.appendChild(u);
      for (var i = 0; i < Math.min(st.decor.count, 10); i++) { var a = (i / 10) * Math.PI * 2; g.appendChild(svg("circle", { cx: (Math.cos(a) * 9.6).toFixed(2), cy: (Math.sin(a) * 9.6).toFixed(2), r: 0.9, fill: "#fff", opacity: 0.9 })); }
      g.appendChild(svg("text", { y: 13.6, "text-anchor": "middle", class: "flat-label" }, st.label));
      var go = function () { openStop(st.key, g); };
      g.addEventListener("click", go); g.addEventListener("keydown", function (e) { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); go(); } });
      root2.appendChild(g);
    });
    viewport.appendChild(root2);
  }

  // ------------------------------------------------------------------ rotating friends (map avatars + open sheet card)
  function startRotation() {
    if (!data.settings.rotation) return;
    timers.push(setInterval(function () {
      if (document.hidden) return;
      Object.keys(labelEls).forEach(function (k) {
        var s = STOPS()[k], av = labelEls[k].querySelector(".w3d-char"); if (!s || !av) return;
        var next = s.chars[slotIndex(k, s.chars.length, data.rotation_seconds)];
        if (next && av.getAttribute("src") !== next) swapImg(av, next);
      });
      if (sheetFriends) sheetFriends.update();
    }, 15000));
  }
  function swapImg(img, src) { img.classList.add("is-out"); setTimeout(function () { img.src = src; img.classList.remove("is-out"); }, animationOn() ? 250 : 0); }

  // ------------------------------------------------------------------ stop sheet
  var sheetFriends = null;
  function offset() { return { x: 0, z: 3.4 }; }                          // the sheet covers the lower part of the map, so the island sits in the upper part
  function openStop(key, from) {
    var s = STOPS()[key]; if (!s) return;
    if (!preview) MM.activity.setStop(key);
    closeGear(true);
    lastFocus = from || lastFocus || document.activeElement; openKey = key; tick();
    if (scene) scene.focus(key, offset());
    stage.classList.add("sheet-open"); sheet.hidden = false; sheet.className = "w3d-sheet open"; sheet.style.setProperty("--c", s.color);
    sheet.replaceChildren(sheetHead(s), el("p", "w3d-blurb", "Loading…"));
    sheet.querySelector("#w3d-sheet-title").focus({ preventScroll: true });
    MM.api(apiRoot + "/stop/" + key).then(function (d) { if (openKey === key) renderSheet(s, d); }).catch(function (e) { if (openKey === key) sheet.appendChild(el("p", "notice", e.message || "That place couldn't open right now.")); });
  }
  function sheetHead(s) {
    var h = el("header", "w3d-sheet__head"), t = el("h3"); t.id = "w3d-sheet-title"; t.tabIndex = -1; t.textContent = s.label;
    var bub = el("span", "w3d-bubble"); bub.appendChild(ic(s.icon));
    h.append(bub, t, btn("w3d-close", null, "x", function () { closeSheet(); }, "Close " + s.label)); return h;
  }
  function closeSheet(quiet) {
    if (!openKey && !quiet) return;
    openKey = null; sheetFriends = null; sheet.hidden = true; sheet.replaceChildren(); stage.classList.remove("sheet-open");
    if (!preview) MM.activity.setStop("home");
    if (window.MMAsset3D) window.MMAsset3D.closeAll();
    if (scene) scene.unfocus();
    if (lastFocus && lastFocus.focus && document.contains(lastFocus)) lastFocus.focus({ preventScroll: true });
  }
  function renderSheet(s, d) {
    var head = sheetHead(s), body = el("div", "w3d-sheet__body");
    if (d.interior) { var ban = el("img", "w3d-interior"); ban.src = d.interior; ban.alt = ""; body.appendChild(ban); }
    body.appendChild(el("p", "w3d-blurb", d.blurb));
    // friends: rotating art characters
    sheetFriends = null;
    if (d.characters.length) {
      var card = el("div", "w3d-friend"), im = el("img"), cap = el("div", "w3d-friend__cap"), name = el("strong"), note = el("span"), disc = el("small");
      im.alt = ""; cap.append(name, note, disc); card.append(im, cap);
      var idx = slotIndex(d.key, d.characters.length, d.rotation_seconds);
      var show = function (i, animate) {
        var c = d.characters[i % d.characters.length]; if (animate && animationOn()) card.classList.add("is-out");
        setTimeout(function () { im.src = c.url; im.alt = c.name || ""; name.textContent = c.name || ""; note.textContent = c.caption || ""; disc.textContent = c.disclaimer || ""; card.classList.remove("is-out"); }, animate && animationOn() ? 220 : 0);
      };
      show(idx, false);
      if (d.characters.length > 1) {
        card.appendChild(btn("btn small", "Meet another friend", "sparkles", function () { idx++; show(idx, true); }));
        if (d.rotation) sheetFriends = { update: function () { var n = slotIndex(d.key, d.characters.length, d.rotation_seconds); if (n !== idx % d.characters.length) { idx = n; show(idx, true); } } };
      }
      body.appendChild(card);
    }
    // friends: approved 3D models
    if (d.friends3d.length) {
      var row = el("div", "a3d-row");
      d.friends3d.forEach(function (f) {
        var a = el("div", "a3d"); a.setAttribute("data-asset3d", ""); a.dataset.glb = f.glb; a.dataset.clips = JSON.stringify(f.clips); a.dataset.name = f.name;
        var st = el("button", "a3d-start"); st.type = "button"; st.setAttribute("aria-label", "Meet " + (f.name || "this friend") + " in 3D"); st.append(el("span", null, f.name || "Friend"), el("small", null, "Tap to meet"));
        var sg = el("div", "a3d-stage"); sg.hidden = true; a.append(st, sg); if (f.caption) a.appendChild(el("p", "small muted", f.caption)); row.appendChild(a);
      });
      body.appendChild(row);
    }
    // chips (sports zones, ice-cream flavours) + shelf
    var chipsData = d.zones.length ? d.zones : d.flavors, q = "", shelfHost = null;
    if (chipsData.length) {
      var chips = el("div", "w3d-chips"); chips.setAttribute("role", "group"); chips.setAttribute("aria-label", d.zones.length ? "Sports" : "Flavours");
      var mk = function (label, val) {
        var c = el("button", "chip", label); c.type = "button"; c.setAttribute("aria-pressed", String(val === q));
        c.addEventListener("click", function () { q = val; chips.querySelectorAll("button").forEach(function (x) { x.setAttribute("aria-pressed", String(x === c)); }); if (shelfHost) shelfHost.load(); }); return c;
      };
      chips.appendChild(mk("All", ""));
      chipsData.forEach(function (z) { chips.appendChild(mk(z.key.charAt(0).toUpperCase() + z.key.slice(1), z.q)); });
      chips.firstChild.setAttribute("aria-pressed", "true"); body.appendChild(chips);
    }
    var caregiverView = root.dataset.canSeeActivity === "1" && !preview;               // the detailed history panel: caregivers only (also enforced by the server)
    var childView = document.body.dataset.role === "child";
    var who = (data.child && data.child.name) || "your child";
    if (caregiverView) body.appendChild(activityPanel(s));                              // WATCHED, first, with details and filters
    else body.appendChild(watchedStrip(d, childView ? "You watched" : "Watched by " + who));
    if (d.shelf) {
      body.appendChild(el("h4", "w3d-sub w3d-rec-title", childView ? "Try something new" : "Recommended"));
      shelfHost = shelf(d, function () { return q; }); body.appendChild(shelfHost.el);
    }
    if (d.favorites) {
      body.appendChild(el("h4", "w3d-sub", "My favourites"));
      var fg = el("div", "tiles"); body.appendChild(fg);
      if (d.favorites.length) MM.renderItems(fg, d.favorites, { readOnly: preview }); else body.appendChild(el("p", "muted", preview ? "No favorites here yet." : "Tap the heart on anything you love and it will wait for you here."));
    }
    sheet.replaceChildren(head, body);
    sheet.querySelector("#w3d-sheet-title").focus({ preventScroll: true });
    if (window.MMAsset3D) window.MMAsset3D.scan(sheet);
  }

  // ------------------------------------------------------------------ what the child actually did at this stop (caregivers)
  var ACT_TYPES = [["all", "All activity"], ["video", "Videos"], ["song", "Music"], ["picture", "Pictures"], ["short", "Shots & clips"]];
  var TZ = -new Date().getTimezoneOffset();
  function actDur(sec) { return sec < 60 ? sec + " sec" : sec < 3600 ? Math.round(sec / 60) + " min" : (Math.round(sec / 360) / 10) + " h"; }
  function actDate(iso, time) { var d = new Date(iso + "T12:00:00"); return d.toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" }) + (time ? " · " + time : ""); }
  function plural(n, w) { return n + " " + w + (n === 1 ? "" : "s"); }
  function activityPanel(s) {
    var wrap = el("section", "w3d-act"); wrap.setAttribute("aria-label", "What " + ((data.child && data.child.name) || "your child") + " did at " + s.label);
    var st = { type: "all", start: "", end: "", page: 1, busy: false, hasMore: false };
    var head = el("div", "w3d-act__head"); head.append(el("h4", "w3d-sub", "Watched by " + ((data.child && data.child.name) || "your child")), el("p", "small muted", "Exactly what was opened here, newest first. Recommendations are below."));
    var chips = el("div", "w3d-chips w3d-act__chips"); chips.setAttribute("role", "group"); chips.setAttribute("aria-label", "Type of activity");
    var chipEls = {};
    ACT_TYPES.forEach(function (t) { var c = el("button", "chip", t[1]); c.type = "button"; c.setAttribute("aria-pressed", String(t[0] === "all")); c.dataset.type = t[0]; chipEls[t[0]] = c;
      c.addEventListener("click", function () { st.type = t[0]; st.page = 1; Object.keys(chipEls).forEach(function (k) { chipEls[k].setAttribute("aria-pressed", String(k === st.type)); }); load(false); }); chips.appendChild(c); });
    var when = el("select", "w3d-act__when"); when.setAttribute("aria-label", "Date range");
    [["all", "Any time"], ["7", "Last 7 days"], ["30", "Last 30 days"], ["custom", "Choose dates…"]].forEach(function (o) { var op = el("option", null, o[1]); op.value = o[0]; when.appendChild(op); });
    var from = el("input"), to = el("input"); from.type = to.type = "date"; from.setAttribute("aria-label", "From date"); to.setAttribute("aria-label", "To date");
    var custom = el("span", "w3d-act__custom"); custom.hidden = true; custom.append(from, el("span", null, "to"), to);
    function iso(d) { return new Date(d.getTime() - d.getTimezoneOffset() * 60000).toISOString().slice(0, 10); }
    function applyRange() {
      var now = new Date();
      if (when.value === "all") { st.start = st.end = ""; }
      else if (when.value === "custom") { st.start = from.value; st.end = to.value; }
      else { var a = new Date(now); a.setDate(a.getDate() - (+when.value - 1)); st.start = iso(a); st.end = iso(now); }
      st.page = 1; custom.hidden = when.value !== "custom"; load(false);
    }
    when.addEventListener("change", applyRange); from.addEventListener("change", applyRange); to.addEventListener("change", applyRange);
    var bar = el("div", "w3d-act__bar"); bar.append(chips, when, custom);
    var other = el("p", "small muted w3d-act__other"), list = el("div", "w3d-act__list"), more = btn("btn", "Show more", null, function () { load(true); }); more.hidden = true;
    var detail = el("div", "w3d-act__detail"); detail.hidden = true;
    wrap.append(head, bar, other, list, more, detail);

    function empty(msg) { list.replaceChildren(el("div", "w3d-act__empty", msg)); st.hasMore = false; more.hidden = true; }
    function card(it) {
      var c = el("button", "w3d-act__card"); c.type = "button"; c.setAttribute("aria-label", "Open details for " + it.content.title);
      var th = el("span", "w3d-act__thumb"); if (it.content.thumbnail_url) { var im = el("img"); im.src = it.content.thumbnail_url; im.alt = ""; im.loading = "lazy"; im.referrerPolicy = "no-referrer"; th.appendChild(im); }
      th.appendChild(el("span", "w3d-act__tag", { video: "Video", song: "Song", picture: "Picture", short: "Shot" }[it.content.type] || ""));
      var b = el("span", "w3d-act__body"), t = el("strong", null, it.content.title), meta = [];
      if (it.artist) meta.push(it.artist); if (it.content.category_label) meta.push(it.content.category_label);
      b.append(t, el("small", null, meta.join(" · ")));
      var facts = [], type = it.content.type;
      if (type === "song") { facts.push(plural(it.plays, "play")); if (it.minutes) facts.push("listened " + actDur(it.seconds)); }
      else if (type === "picture") { facts.push(plural(it.interactions, "interaction")); if (it.seconds >= 5) facts.push("viewed " + actDur(it.seconds)); }
      else { facts.push(plural(it.views, "view")); if (it.seconds) facts.push("watched " + actDur(it.seconds)); if (type === "short" && it.replays) facts.push(plural(it.replays, "replay")); if (it.completion_pct != null && type !== "short") facts.push(it.completion_pct + "% played"); }
      b.append(el("small", "w3d-act__facts", facts.join(" · ")), el("small", "w3d-act__date", "Last: " + actDate(it.last_date, it.last_time)));
      c.append(th, b); c.addEventListener("click", function () { showDetail(it); }); return c;
    }
    function load(append) {
      if (st.busy) return; st.busy = true;
      if (!append) list.replaceChildren(MM.skeletons(3));
      var p = new URLSearchParams({ type: st.type, page: st.page, tz: TZ }); if (st.start) p.set("start", st.start); if (st.end) p.set("end", st.end);
      MM.api(apiRoot + "/stop/" + s.key + "/activity?" + p).then(function (r) {
        ACT_TYPES.forEach(function (t) { chipEls[t[0]].textContent = t[1] + " (" + (r.counts[t[0]] || 0) + ")"; });
        var o = r.other, bits = []; if (o.favorites) bits.push(plural(o.favorites, "favourite")); if (o.likes) bits.push(plural(o.likes, "like")); if (o.skips) bits.push(plural(o.skips, "skip")); if (o.explored) bits.push("explored " + plural(o.explored, "time"));
        other.textContent = bits.length ? "Also here: " + bits.join(" · ") : ""; other.hidden = !bits.length;
        if (!append) list.replaceChildren();
        if (!r.any_activity) { if (st.start || st.end) empty("No activity in this time. Try a longer period."); else empty("No activity recorded here yet. As your child explores the application, their activities will appear here."); bar.hidden = !(st.start || st.end); return; }
        bar.hidden = false;
        if (!r.items.length && !append) { empty("Nothing matches these filters."); return; }
        r.items.forEach(function (it) { list.appendChild(card(it)); });
        st.hasMore = r.has_more; more.hidden = !r.has_more; st.page = r.page + 1;
      }).catch(function (e) { if (!append) empty(e.message || "Couldn't load the activity right now."); }).then(function () { st.busy = false; });
    }
    function showDetail(it) {
      list.hidden = bar.hidden = other.hidden = more.hidden = true; detail.hidden = false; detail.replaceChildren(el("p", "muted", "Loading…"));
      var p = new URLSearchParams({ tz: TZ }); if (st.start) p.set("start", st.start); if (st.end) p.set("end", st.end);
      var back = btn("btn small", "Back to the list", "chevron-left", function () { detail.hidden = true; detail.replaceChildren(); list.hidden = bar.hidden = false; other.hidden = !other.textContent; more.hidden = !st.hasMore; });
      MM.api(apiRoot + "/stop/" + s.key + "/activity/" + it.content.id + "?" + p).then(function (r) {
        var v = r.viewer, box = el("div", "w3d-act__view");
        if (v.type === "picture" && v.thumb) { var im = el("img", "w3d-act__big"); im.src = v.thumb; im.alt = v.title; im.referrerPolicy = "no-referrer"; box.appendChild(im); }
        else if (v.embed) { var f = el("iframe", "w3d-act__embed" + (v.type === "short" ? " is-short" : "")); f.src = v.embed; f.title = v.title; f.loading = "lazy"; f.allow = "encrypted-media; picture-in-picture; fullscreen"; f.setAttribute("allowfullscreen", ""); f.referrerPolicy = "strict-origin-when-cross-origin"; box.appendChild(f); }
        else if (v.thumb) { var i2 = el("img", "w3d-act__big"); i2.src = v.thumb; i2.alt = ""; box.appendChild(i2); }
        var t = r.totals, sum = [plural(t.views, "view"), t.minutes ? actDur(Math.round(t.minutes * 60)) + " in total" : null, t.replays ? plural(t.replays, "replay") : null, t.completion_pct != null ? t.completion_pct + "% played" : null].filter(Boolean);
        var recs = el("ul", "w3d-act__records");
        r.records.forEach(function (x) {
          var li = el("li"), what = x.action_label + (x.seconds && x.engagement ? " · " + actDur(x.seconds) : "") + (x.completion_pct != null ? " · " + x.completion_pct + "%" : "") + (x.replays ? " · " + plural(x.replays, "replay") : "");
          li.append(el("span", null, actDate(x.date, x.time)), el("b", null, what)); recs.appendChild(li);
        });
        var links = el("div", "w3d-act__links"); if (v.url) { var a = el("a", "btn small", "Open original"); a.href = v.url; a.target = "_blank"; a.rel = "noopener noreferrer"; links.appendChild(a); }
        detail.replaceChildren(back, el("h4", "w3d-sub", r.content.title), el("p", "small muted", [r.artist, r.content.category_label].filter(Boolean).join(" · ")), box, el("p", "w3d-act__sum", sum.join(" · ")), el("h5", "w3d-act__h", "Every time it was opened"), recs, links);
      }).catch(function (e) { detail.replaceChildren(back, el("p", "notice", e.message || "That record couldn't open.")); });
    }
    load(false);
    return wrap;
  }

  // ------------------------------------------------------------------ "Watched" strip: exactly what the child opened here (child, parent preview, share link)
  function watchedStrip(d, title) {
    var w = d.watched || { items: [], total: 0 }, sec = el("section", "w3d-watched");
    sec.setAttribute("aria-label", title);
    var head = el("h4", "w3d-sub", title + (w.total ? " (" + w.total + ")" : "")); sec.appendChild(head);
    if (!w.items.length) { sec.appendChild(el("p", "w3d-watched__none", preview ? "Nothing watched here yet." : "Things you watch here will show up first.")); return sec; }
    var grid = el("div", "tiles w3d-watched__grid"), shown = 8, more = null;
    function note(i) {
      var bits = [(i.w_views === 1 ? "Watched once" : "Watched " + i.w_views + " times")];
      if (!document.body.dataset.role || document.body.dataset.role !== "child") { if (i.w_minutes) bits.push(i.w_minutes < 1 ? "under a minute" : Math.round(i.w_minutes) + " min"); }
      return bits.join(" · ");
    }
    function draw() {
      grid.replaceChildren();
      w.items.slice(0, shown).forEach(function (i) {
        var c = MM.card(i, { readOnly: preview }); c.classList.add("is-watched");
        var tag = el("span", "w3d-watched__tag"); tag.append(ic("check", "sm"), el("span", null, "Watched")); c.appendChild(tag);
        c.appendChild(el("small", "w3d-watched__note", note(i))); grid.appendChild(c);
      });
      if (more) more.hidden = shown >= w.items.length;
    }
    more = btn("btn small", "Show more watched", null, function () { shown += 8; draw(); }); more.hidden = true;
    sec.append(grid, more); draw(); return sec;
  }
  function shelf(d, getQ) {
    var wrap = el("div", "w3d-shelf"), grid = el("div", "tiles"), more = btn("btn", "Show more", null, function () { load(true); });
    var seeAll = { "/api/pictures": "/pictures", "/api/videos": "/videos", "/api/shots": "/shots", "/api/music": "/music" }[d.shelf.endpoint];
    var page = 1, busy = false, gen = 0, seen = {}, watchedIds = {};
    ((d.watched && d.watched.items) || []).forEach(function (i) { watchedIds[i.id] = 1; });
    more.hidden = true; wrap.append(grid, more);
    if (seeAll && !preview) { var a = el("a", "w3d-all", "See all "); a.href = seeAll + (d.shelf.params.category ? "?category=" + encodeURIComponent(d.shelf.params.category) : ""); a.appendChild(ic("chevron-right", "sm")); wrap.appendChild(a); }
    function load(append) {
      if (busy) return; busy = true; var my = append ? gen : ++gen;
      if (!append) { grid.replaceChildren(MM.skeletons(4)); page = 1; seen = Object.assign({}, watchedIds); }
      var params = new URLSearchParams(Object.assign({}, d.shelf.params, { page: page })); if (getQ()) params.set("q", getQ());
      MM.api(d.shelf.endpoint + "?" + params).then(function (r) {
        if (my !== gen) return;
        var fresh = r.items.filter(function (i) { if (seen[i.id]) return false; seen[i.id] = 1; return true; });
        if (append) fresh.forEach(function (i) { grid.appendChild(MM.card(i, { readOnly: preview })); }); else MM.renderItems(grid, fresh, { readOnly: preview });
        more.hidden = !(r.more !== false && r.items.length); page++;
        if (r.notice && !append) MM.notice(wrap, r.notice);
      }).catch(function (e) { if (my === gen) grid.replaceChildren(el("div", "empty", e.message || "Couldn't load this right now.")); }).then(function () { busy = false; });
    }
    load(false);
    return { el: wrap, load: function () { busy = false; load(false); } };
  }

  // ------------------------------------------------------------------ caregiver controls
  function toggleGear() { if (gear.hidden) openGear(); else closeGear(); }
  function closeGear(quiet) {
    if (gear.hidden) return; gear.hidden = true; gear.replaceChildren(); var g = $("w3d-gear-btn"); if (g) { g.setAttribute("aria-expanded", "false"); if (!quiet) g.focus({ preventScroll: true }); }
  }
  function field(label, control, hint) { var w = el("div", "field"), l = el("label", null, label); control.id = control.id || "g-" + Math.random().toString(36).slice(2, 8); l.htmlFor = control.id; w.append(l, control); if (hint) w.appendChild(el("p", "small muted", hint)); return w; }
  function checks(name, items, current, labelFn) {
    var box = el("div", "w3d-checks"); box.setAttribute("role", "group");
    items.forEach(function (it) {
      var key = it.key || it, l = el("label", "choice"), c = el("input"); c.type = "checkbox"; c.value = key; c.name = name; c.checked = current.indexOf(key) >= 0;
      l.append(c, el("span", null, labelFn ? labelFn(it) : (it.label || key))); box.appendChild(l);
    });
    return box;
  }
  function openGear() {
    closeSheet(true); var S = data.settings, O = data.options;
    gear.hidden = false; $("w3d-gear-btn").setAttribute("aria-expanded", "true");
    var form = el("form", "w3d-gear__form"); form.autocomplete = "off";
    var title = el("h3"); title.id = "w3d-gear-title"; title.tabIndex = -1; title.textContent = "World settings";
    var head = el("header", "w3d-sheet__head"); head.append(title, btn("w3d-close", null, "x", function () { closeGear(); }, "Close settings"));
    var theme = el("select"); [["auto", "Automatic (from choices)"]].concat(O.themes.map(function (t) { return [t.key, t.label]; })).forEach(function (o) { var op = el("option", null, o[1]); op.value = o[0]; op.selected = S.theme === o[0]; theme.appendChild(op); });
    var island = el("select"); (O.islands || []).length && [["auto", "Automatic (default island)"]].concat(O.islands.map(function (i) { return [i.key, i.label]; })).forEach(function (o) { var op = el("option", null, o[1]); op.value = o[0]; op.selected = (S.island || "auto") === o[0]; island.appendChild(op); });
    var strength = el("select"); O.strengths.forEach(function (k) { var op = el("option", null, { light: "Light: fewer decorations", balanced: "Balanced", strong: "Strong: more decorations" }[k]); op.value = k; op.selected = S.strength === k; strength.appendChild(op); });
    var interests = checks("interests", O.interests, S.interests), zones = checks("zones", O.zones, S.sports_zones, function (z) { return z.charAt(0).toUpperCase() + z.slice(1); });
    var hidden = checks("hidden", O.stops, S.hidden_stops), decor = checks("decor", O.stops, S.decor_off);
    function toggle(name, label, on) { var l = el("label", "choice"), c = el("input"); c.type = "checkbox"; c.name = name; c.checked = on; l.append(c, el("span", null, label)); return l; }
    var reasonBox = el("p", "small w3d-why"); reasonBox.append(el("strong", null, "Why " + data.theme.label + "? "), document.createTextNode(data.theme.reason));
    var reset = btn("btn small", "Reset theme", null, function () {
      if (!window.confirm("Start choosing the theme from scratch? Choices, favourites and decorations are kept.")) return;
      MM.api("/api/world/reset-theme", { json: {} }).then(function (d) { applyData(d, "Theme reset."); }).catch(function (e) { MM.toast(e.message); });
    });
    var flatNow = store("mm-world-flat") === "1";
    form.append(head, reasonBox, reset,
      field("World style", theme, "Automatic only changes after repeated positive choices, and a close second keeps the world mixed."),
      (O.islands || []).length ? field("Island look", island, "Pick the shape and scenery of the islands in My World.") : el("span"), field("Decoration strength", strength),
      el("fieldset", "w3d-fs"), el("fieldset", "w3d-fs"), el("fieldset", "w3d-fs"), el("fieldset", "w3d-fs"), el("fieldset", "w3d-fs"));
    var fs = form.querySelectorAll("fieldset");
    fs[0].append(el("legend", null, "Interests I confirm"), interests, el("p", "small muted", "Confirming an interest can unlock its place and style. Football and Basketball styles also need a sports zone below."));
    fs[1].append(el("legend", null, "Sports zones"), zones);
    fs[2].append(el("legend", null, "Places to hide"), hidden, el("p", "small muted", "Home always stays."));
    fs[3].append(el("legend", null, "Turn decorations off for"), decor);
    fs[4].append(el("legend", null, "Comfort"), toggle("rotation", "Rotate friends every few minutes", S.rotation), toggle("animation", "Gentle animation (water, clouds, bobbing)", S.animation),
      toggle("sound", "Soft sounds", S.sound), toggle("real_people", "Show licensed pictures of real people", S.real_people),
      mode === "3d" || flatNow ? toggle("flat", "Use the simple map instead of 3D", flatNow) : el("span"), el("p", "small muted", "Reduced motion in Settings always wins over animation."));
    var save = el("button", "btn primary block", "Save"); save.type = "submit"; form.appendChild(save);
    form.addEventListener("submit", function (e) {
      e.preventDefault();
      var f = new FormData(form), all = function (n) { return f.getAll(n); }, on = function (n) { return f.get(n) !== null; };
      var body = { theme: f.get("theme") || theme.value, strength: strength.value, interests: all("interests"), sports_zones: all("zones"), hidden_stops: all("hidden"), decor_off: all("decor"),
                   rotation: on("rotation"), animation: on("animation"), sound: on("sound"), real_people: on("real_people") };
      body.theme = theme.value;
      if ((O.islands || []).length) body.island = island.value;
      var wantFlat = on("flat");
      MM.api("/api/world/settings", { json: body }).then(function (d) {
        if (mode === "3d" || flatNow) { store("mm-world-flat", wantFlat ? "1" : "0"); mode = wantFlat ? "flat" : decideMode(); }
        applyData(d, "World updated.");
      }).catch(function (err) { MM.toast(err.message || "That could not be saved."); });
    });
    gear.replaceChildren(form); title.focus({ preventScroll: true });
  }
  function applyData(d, msg) { data = d; closeGear(true); mount(); if (msg) MM.toast(msg); }

  document.addEventListener("keydown", function (e) { if (e.key === "Escape") { if (!gear.hidden) closeGear(); else if (openKey) closeSheet(); } });
  document.addEventListener("visibilitychange", function () { if (scene) scene.setAnimation(animationOn() && !document.hidden); });
  // The administrator can change the island for everyone. When this screen comes back into view (another device or an old tab),
  // check the server and reload the map if the island changed.
  function islandId(d) { return d && d.island_base ? String(d.island_base.id) : "classic"; }
  document.addEventListener("visibilitychange", function () {
    if (preview || document.hidden || !gear || !gear.hidden) return;
    MM.api(apiRoot).then(function (d) { if (d && islandId(d) !== islandId(data)) applyData(d, "My World has a new island."); }).catch(function () { /* offline: keep the current map */ });
  });

  mode = decideMode();
  mount();
  window.MMWorldUI = { mode: function () { return mode; }, open: openStop, data: function () { return data; }, kit: function () { return scene ? scene.kit() : null; } };     // used by tests
})();
