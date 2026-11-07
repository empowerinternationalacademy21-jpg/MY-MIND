/* Caretaker Activity & interests dashboard. All numbers come from /api/caretaker/* (real recorded activity); this file only draws them.
   Text is always set with textContent. Refreshes itself every 45 s while the tab is visible. */
(function () {
  "use strict";
  var root = document.getElementById("ad-root");
  if (!root || !window.CTCharts) return;
  var C = window.CTCharts, h = C.el, $ = function (id) { return document.getElementById(id); };
  var TZ = -new Date().getTimezoneOffset();
  var TYPE_COLORS = { video: "#ef6f9a", short: "#9a5bd9", song: "#ff9d45", picture: "#3fd9c8", other: "#9aa3ad" };
  var TYPE_LABELS = { video: "Videos", short: "Shorts", song: "Songs", picture: "Pictures", other: "Other" };
  var STATUS = { emerging: "New", increasing: "Growing", steady: "Steady", fading: "Easing", exploring: "Exploring" };
  var state = { range: "7", start: "", end: "", day: "", child: root.dataset.child, type: "", action: "", category: "", q: "", hs: "", he: "", page: 1, summary: null };
  var cats = {};

  function api(path, params) {
    var p = new URLSearchParams(params || {});
    p.set("tz", TZ); p.set("child", state.child);
    return fetch(path + "?" + p.toString(), { credentials: "same-origin", headers: { Accept: "application/json" }, cache: "no-store" })
      .then(function (r) { if (!r.ok) throw new Error(r.status === 404 ? "Not available." : "Could not load this right now."); return r.json(); });
  }
  function rangeParams() {
    var p = { range: state.range };
    if (state.range === "custom") { p.start = state.start; p.end = state.end; }
    if (state.day) p.day = state.day;
    return p;
  }
  function clear(n) { while (n.firstChild) n.removeChild(n.firstChild); return n; }
  function put(id, node) { var t = clear($(id)); t.appendChild(node); }
  function fail(id, msg) { put(id, C.empty(msg || "Could not load this right now.")); }
  function pct(v) { return v == null ? "" : (v > 0 ? "+" : "") + v + "%"; }
  function dayLabel(iso) { var d = new Date(iso + "T12:00:00"); return d.toLocaleDateString(undefined, { day: "numeric", month: "short" }); }
  function ago(iso) {
    var s = Math.max(0, Math.round((Date.now() - new Date(iso).getTime()) / 1000));
    return s < 60 ? "just now" : s < 3600 ? Math.floor(s / 60) + " min ago" : s < 86400 ? Math.floor(s / 3600) + " h ago" : new Date(iso).toLocaleString();
  }
  function dur(sec) { return sec < 60 ? sec + " sec" : C.fmtMin(sec / 60); }

  /* ---------- content tile (real thumbnail) ---------- */
  function thumb(content, cls) {
    var box = h("span", cls || "ad-thumb");
    if (content && content.thumbnail_url) { var i = h("img"); i.src = content.thumbnail_url; i.alt = ""; i.loading = "lazy"; i.referrerPolicy = "no-referrer"; box.appendChild(i); }
    return box;
  }

  /* ---------- stats ---------- */
  function card(label, value, sub) {
    var a = h("article", "ad-stat"); a.append(h("span", "ad-stat-label", label), h("strong", null, value));
    if (sub) a.appendChild(h("small", null, sub)); return a;
  }
  function renderStats(d) {
    var s = d.stats, box = clear($("ad-stats"));
    var wk = s.week_change_pct == null ? "No earlier week to compare" : pct(s.week_change_pct) + " vs previous week";
    var mo = s.month_change_pct == null ? "No earlier month to compare" : pct(s.month_change_pct) + " vs previous 30 days";
    [card("Engagement time", C.fmtMin(s.total_minutes), s.sessions + " session" + (s.sessions === 1 ? "" : "s")),
     card("Average per day", C.fmtMin(s.avg_daily_minutes), s.active_days + " of " + s.days + " days active"),
     card("Most active day", s.most_active_day ? dayLabel(s.most_active_day.date) : "–", s.most_active_day ? C.fmtMin(s.most_active_day.minutes) : "No activity yet"),
     card("Most active time", s.most_active_period ? s.most_active_period.label.split(" (")[0] : "–", s.most_active_period ? C.fmtMin(s.most_active_period.minutes) : ""),
     card("This week", C.fmtMin(s.week_minutes), wk), card("This month", C.fmtMin(s.month_minutes), mo),
     card("Favourite video topic", s.top_video_category ? s.top_video_category.label : "–", s.top_video_category ? C.fmtMin(s.top_video_category.minutes) : ""),
     card("Favourite music topic", s.top_music_category ? s.top_music_category.label : "–", s.top_music_category ? C.fmtMin(s.top_music_category.minutes) : ""),
     card("Favourite picture topic", s.top_picture_category ? s.top_picture_category.label : "–", s.top_picture_category ? C.fmtMin(s.top_picture_category.minutes) : ""),
     card("Most replayed", s.most_replayed ? s.most_replayed.content.title : "–", s.most_replayed ? s.most_replayed.plays + " plays" : "Nothing replayed yet"),
     card("Finished", String(s.completions), s.replays + " replay" + (s.replays === 1 ? "" : "s"))
    ].forEach(function (c) { box.appendChild(c); });
    if (s.measured_share != null && s.measured_share < 100) {
      box.appendChild(h("p", "ad-note", s.measured_share + "% of this time was measured from the player (playing time only). The rest is the time the viewer was open."));
    }
  }

  /* ---------- graphs ---------- */
  function renderGraphs(d) {
    var typeNames = ["video", "short", "song", "picture"];
    // 1 daily by hour, stacked by type
    var present = typeNames.filter(function (t) { return d.day_graph.some(function (x) { return x.by_type[t]; }); });
    if (!d.day_graph.some(function (x) { return x.minutes > 0; })) put("ad-g1", C.empty("No activity on " + dayLabel(d.range.focus_day) + "."));
    else put("ad-g1", C.columns({ label: "Engagement by hour", labels: d.day_graph.map(function (x) { return String(x.hour).padStart(2, "0") + ":00"; }),
      shortLabels: d.day_graph.map(function (x) { return String(x.hour).padStart(2, "0"); }), stacked: true,
      series: present.map(function (t) { return { name: TYPE_LABELS[t], color: TYPE_COLORS[t], values: d.day_graph.map(function (x) { return x.by_type[t] || 0; }) }; }) }));
    $("ad-g1-sub").textContent = "Engagement on " + dayLabel(d.range.focus_day) + ", by hour of your local day";
    // 2 weekly
    if (!d.week_graph.some(function (x) { return x.minutes > 0; })) put("ad-g2", C.empty("No activity in these 7 days."));
    else { var peak = d.week_graph.reduce(function (a, x, i) { return x.minutes > d.week_graph[a].minutes ? i : a; }, 0);
      put("ad-g2", C.columns({ label: "Engagement over 7 days", labels: d.week_graph.map(function (x) { return x.weekday + " " + dayLabel(x.date); }), shortLabels: d.week_graph.map(function (x) { return x.weekday; }),
        series: [{ name: "Engagement", color: "#ff9d45", values: d.week_graph.map(function (x) { return x.minutes; }) }], highlight: peak, onSelect: function (i) { setDay(d.week_graph[i].date); } })); }
    // 3 monthly
    $("ad-g3-sub").textContent = d.month_label + ", day by day";
    if (!d.month_graph.some(function (x) { return x.minutes > 0; })) put("ad-g3", C.empty("No activity this month yet."));
    else put("ad-g3", C.lines({ label: "Engagement over the month", labels: d.month_graph.map(function (x) { return dayLabel(x.date); }), shortLabels: d.month_graph.map(function (x) { return x.date.slice(8); }),
      series: [{ name: "Engagement", color: "#3fd9c8", values: d.month_graph.map(function (x) { return x.minutes; }) }] }));
    // 4 distribution by interactions
    if (!d.distribution.length) put("ad-g4", C.empty("No categorised activity yet."));
    else put("ad-g4", C.hbars({ label: "Interest distribution", max: 100, items: d.distribution.slice(0, 8).map(function (x) { return { label: x.label, value: x.percent, color: x.color, text: x.percent + "%", sub: x.interactions + " interaction" + (x.interactions === 1 ? "" : "s") }; }) }));
    // 5 content types
    var tt = d.types.filter(function (t) { return t.minutes > 0 || t.sessions > 0; });
    if (!tt.length) put("ad-g5", C.empty("No activity yet."));
    else put("ad-g5", C.hbars({ label: "Content type comparison", items: d.types.map(function (t) { return { label: t.label, value: t.minutes, color: TYPE_COLORS[t.type], text: C.fmtMin(t.minutes), sub: t.sessions + (t.type === "other" ? " visits, searches and explorations" : " session" + (t.sessions === 1 ? "" : "s")) }; }) }));
    // 6 development
    if (!d.development.enough) put("ad-g6", C.empty(d.development.message));
    else put("ad-g6", C.lines({ label: "Interest development by week", labels: d.development.weeks.map(function (w) { return "Week of " + dayLabel(w); }), shortLabels: d.development.weeks.map(dayLabel),
      series: d.development.series.map(function (x) { return { name: x.label, color: x.color, values: x.values }; }) }));
    // 7 allocation
    var tot = d.allocation.reduce(function (a, x) { return a + x.minutes; }, 0);
    if (!d.allocation.length) put("ad-g7", C.empty("No categorised time yet."));
    else put("ad-g7", C.doughnut({ label: "Time allocation by category", center: C.fmtMin(tot), sub: "categorised", items: d.allocation.slice(0, 8).map(function (x) { return { label: x.label, value: x.minutes, color: x.color }; }) }));
    // 8 most engaging
    if (!d.most_engaging.length) put("ad-g8", C.empty("No content engagement yet."));
    else put("ad-g8", C.hbars({ label: "Most engaging content", fmt: function (v) { return Math.round(v * 10) / 10 + " pts"; },
      items: d.most_engaging.map(function (x) { return { label: x.content.title, value: x.score, thumb: x.content.thumbnail_url, color: "#ff7a1a", sub: C.fmtMin(x.minutes) + " · " + x.completions + " finished · " + x.replays + " replay" + (x.replays === 1 ? "" : "s") }; }) }));
  }

  function renderTrends(d) {
    var t = d.trends, box = clear($("ad-trends"));
    if (!t.available) { box.appendChild(C.empty(t.message)); return; }
    var groups = [["new", "New this period"], ["increasing", "Going up"], ["steady", "Steady"], ["decreasing", "Going down"]], any = false;
    var grid = h("div", "ad-trend-grid");
    groups.forEach(function (g) {
      var rows = t[g[0]]; if (!rows.length) return; any = true;
      var col = h("div", "ad-trend ad-trend--" + g[0]); col.appendChild(h("h3", null, g[1]));
      rows.slice(0, 6).forEach(function (r) {
        var line = h("p"); line.append(h("strong", null, r.label), document.createTextNode(" " + C.fmtMin(r.current_minutes) + (r.change_pct == null ? "" : " (" + pct(r.change_pct) + ")") + " · before: " + C.fmtMin(r.previous_minutes)));
        col.appendChild(line);
      }); grid.appendChild(col);
    });
    box.appendChild(any ? grid : C.empty("Nothing to compare yet."));
  }

  function rankList(title, rows, mk) {
    var s = h("div", "ad-rank"); s.appendChild(h("h3", null, title));
    if (!rows.length) { s.appendChild(C.empty("Nothing yet.")); return s; }
    var ul = h("ul"); rows.forEach(function (r) { ul.appendChild(mk(r)); }); s.appendChild(ul); return s;
  }
  function contentRow(r, sub) {
    var li = h("li"); li.appendChild(thumb(r.content));
    var b = h("div"); b.append(h("strong", null, r.content.title), h("small", null, sub)); li.appendChild(b); return li;
  }
  function renderRankings(d) {
    var r = d.rankings, box = clear($("ad-rankings"));
    box.append(
      rankList("Most watched videos", r.most_watched_videos, function (x) { return contentRow(x, C.fmtMin(x.minutes) + " · " + x.sessions + " view" + (x.sessions === 1 ? "" : "s") + (x.completion_pct != null ? " · " + x.completion_pct + "% played" : "")); }),
      rankList("Most replayed", r.most_replayed, function (x) { return contentRow(x, x.plays + " plays · " + x.replays + " replay" + (x.replays === 1 ? "" : "s")); }),
      rankList("Most listened-to songs", r.most_listened_songs, function (x) { return contentRow(x, C.fmtMin(x.minutes) + " · " + x.sessions + " listen" + (x.sessions === 1 ? "" : "s")); }),
      rankList("Most viewed pictures", r.most_viewed_pictures, function (x) { return contentRow(x, x.sessions + " view" + (x.sessions === 1 ? "" : "s") + " · " + C.fmtMin(x.minutes)); }),
      rankList("Most explored categories", r.most_explored_categories, function (x) { var li = h("li"); var b = h("div"); b.append(h("strong", null, x.label), h("small", null, x.count + " time" + (x.count === 1 ? "" : "s"))); li.appendChild(b); return li; }),
      rankList("Most used features", r.most_used_features, function (x) { var li = h("li"); var b = h("div"); b.append(h("strong", null, x.label), h("small", null, x.visits + " visit" + (x.visits === 1 ? "" : "s"))); li.appendChild(b); return li; }));
  }

  /* ---------- rows used by feed + history ---------- */
  function eventRow(e, withDate) {
    var li = h("li", "ad-row"), btn = h("button", "ad-row-btn"); btn.type = "button";
    btn.appendChild(thumb(e.content));
    var b = h("div", "ad-row-body");
    var title = e.content ? e.content.title : (e.action === "browse" ? (e.category_label || "A category") : e.action === "view" ? e.stop_label : e.action_label);
    b.appendChild(h("strong", null, title));
    var bits = [e.action_label];
    if (e.seconds && (e.engagement || e.action === "view")) bits.push(dur(e.seconds));
    if (e.completion_pct != null) bits.push(e.completion_pct + "% played");
    if (e.replays) bits.push(e.replays + " replay" + (e.replays === 1 ? "" : "s"));
    if (e.category_label) bits.push(e.category_label);
    b.appendChild(h("small", null, bits.join(" · ")));
    btn.appendChild(b);
    var when = h("time", "ad-when", (withDate ? dayLabel(e.date) + " " : "") + e.time); when.setAttribute("datetime", e.iso); btn.appendChild(when);
    btn.setAttribute("aria-label", title + ", " + bits.join(", ") + ", " + e.time);
    btn.addEventListener("click", function () { openDetail(e.id); });
    li.appendChild(btn); return li;
  }

  function renderFeed() {
    return api("/api/caretaker/activity/history", { page: 1, per_page: 12, visits: 0 }).then(function (r) {
      var box = clear($("ad-feed"));
      if (!r.items.length) { box.appendChild(C.empty("No activity recorded yet. It appears here as soon as your child uses MyMind.")); return; }
      var ul = h("ul", "ad-list"); r.items.forEach(function (e) { ul.appendChild(eventRow(e, true)); }); box.appendChild(ul);
    }).catch(function () { fail("ad-feed"); });
  }

  /* ---------- timeline ---------- */
  function renderTimeline() {
    var day = state.day || (state.summary && state.summary.range.focus_day);
    if (!day) return;
    return api("/api/caretaker/activity/timeline", { day: day }).then(function (t) {
      var box = clear($("ad-timeline"));
      $("ad-timeline-sub").textContent = dayLabel(t.date) + (t.first ? " · first activity " + t.first + ", last " + t.last : "") + " · times in your local time";
      if (!t.events.length) { box.appendChild(C.empty("No activity on this day.")); return; }
      var ev = t.events.filter(function (e) { return e.engagement || e.action === "open"; }).map(function (e) {
        return { time: e.time, seconds: e.seconds, color: TYPE_COLORS[e.content_type] || TYPE_COLORS.other, label: (e.content ? e.content.title : e.action_label) + " (" + e.action_label + ")" };
      });
      box.appendChild(C.dayStrip({ events: ev, label: "Timeline of the day" }));
      if (t.by_category.length) box.appendChild(C.hbars({ label: "Time by category", items: t.by_category.map(function (x) { return { label: x.label, value: x.minutes, color: x.color }; }) }));
      var ol = h("ol", "ad-tl");
      t.events.forEach(function (e) {
        var li = h("li"), tm = h("time", null, e.time); li.appendChild(tm); li.appendChild(h("span", "ad-tl-dot"));
        var b = h("div"); b.appendChild(h("strong", null, e.content ? e.content.title : (e.action === "view" ? "Visited " + e.stop_label : e.action_label)));
        b.appendChild(h("small", null, e.action_label + (e.seconds ? " · " + dur(e.seconds) : "") + (e.category_label ? " · " + e.category_label : "") + " · " + e.stop_label));
        li.appendChild(b); li.addEventListener("click", function () { openDetail(e.id); }); ol.appendChild(li);
      });
      box.appendChild(ol);
    }).catch(function () { fail("ad-timeline"); });
  }

  /* ---------- history ---------- */
  function histParams() {
    var p = { page: state.page, per_page: 20 };
    ["type", "action", "category", "q"].forEach(function (k) { if (state[k]) p[k] = state[k]; });
    if (state.hs) p.start = state.hs; if (state.he) p.end = state.he;
    return p;
  }
  function renderHistory() {
    return api("/api/caretaker/activity/history", histParams()).then(function (r) {
      var ul = clear($("ad-history")), pager = clear($("ad-pager"));
      $("ad-history-count").textContent = r.total ? r.total + " record" + (r.total === 1 ? "" : "s") + " · page " + r.page + " of " + r.pages : "";
      if (!r.items.length) { ul.appendChild(h("li", "ad-empty-li", "No activity matches these filters.")); return; }
      r.items.forEach(function (e) { ul.appendChild(eventRow(e, true)); });
      function pb(label, page, disabled) { var b = h("button", "btn small", label); b.type = "button"; b.disabled = disabled; b.addEventListener("click", function () { state.page = page; renderHistory(); $("ad-history-panel").scrollIntoView({ block: "start" }); }); return b; }
      pager.append(pb("Previous", r.page - 1, r.page <= 1), h("span", "small muted", "Page " + r.page + " of " + r.pages), pb("Next", r.page + 1, !r.has_more));
    }).catch(function () { var ul = clear($("ad-history")); ul.appendChild(h("li", "ad-empty-li", "Could not load the history right now.")); });
  }
  function renderPeriods(group) {
    return api("/api/caretaker/activity/series", { group: group }).then(function (r) {
      var box = clear($("ad-periods"));
      if (!r.items.length) return;
      var items = r.items.slice(-8);
      box.appendChild(C.columns({ label: "Engagement by " + group, labels: items.map(function (x) { return x.period; }), shortLabels: items.map(function (x) { return group === "month" ? x.period.slice(2) : x.period.slice(5); }),
        series: [{ name: "Engagement", color: "#ff9d45", values: items.map(function (x) { return x.minutes; }) }] }));
    }).catch(function () { });
  }
  function fillCategories(d) {
    [d.allocation, d.distribution].forEach(function (list) { list.forEach(function (x) { cats[x.category] = x.label; }); });
    var sel = $("ad-category"), cur = sel.value;
    while (sel.options.length > 1) sel.remove(1);
    Object.keys(cats).sort().forEach(function (k) { var o = h("option", null, cats[k]); o.value = k; sel.appendChild(o); });
    sel.value = cur;
  }

  /* ---------- detail dialog: the actual content ---------- */
  function openDetail(id) {
    var dlg = $("ad-dialog"), body = clear($("ad-dialog-body")); body.appendChild(h("p", "muted", "Loading…"));
    if (!dlg.open) dlg.showModal();
    api("/api/caretaker/activity/" + id).then(function (e) {
      clear(body); var v = e.viewer;
      $("ad-dialog-title").textContent = e.content ? e.content.title : e.action_label;
      if (v && v.type === "picture" && v.thumb) { var img = h("img", "ad-big"); img.src = v.thumb; img.alt = v.title; img.referrerPolicy = "no-referrer"; body.appendChild(img); }
      else if (v && v.embed) {
        var f = h("iframe", "ad-embed" + (v.type === "short" ? " is-short" : "")); f.src = v.embed; f.title = v.title; f.loading = "lazy";
        f.allow = "encrypted-media; picture-in-picture; fullscreen"; f.referrerPolicy = "strict-origin-when-cross-origin"; f.setAttribute("allowfullscreen", ""); body.appendChild(f);
      } else if (v && v.thumb) { var im = h("img", "ad-big"); im.src = v.thumb; im.alt = ""; body.appendChild(im); }
      var dl = h("dl", "ad-dl");
      function row(k, val) { if (val == null || val === "") return; dl.append(h("dt", null, k), h("dd", null, val)); }
      row("Action", e.action_label); row("When", new Date(e.iso).toLocaleString()); row("Where", e.stop_label);
      row("Content type", TYPE_LABELS[e.content_type] || ""); row("Category", e.category_label);
      if (e.engagement) { row("Time engaged", dur(e.seconds)); row("Completion", e.completion_pct != null ? e.completion_pct + "%" : "Not reported by the player");
        row("Finished", e.completed ? "Yes" : "No"); row("Pauses / resumes", e.pauses + " / " + e.resumes); row("Replays", String(e.replays));
        row("Time measured from", e.measured ? "Player (playing time only)" : "Time the viewer was open"); }
      var ch = e.content_history;
      if (ch) { row("All sessions with this", ch.sessions + " · " + C.fmtMin(ch.minutes)); row("Replays / finishes", ch.replays + " / " + ch.completions);
        row("Likes / favorites / skips", ch.likes + " / " + ch.favorites + " / " + ch.skips); row("First seen", new Date(ch.first_seen).toLocaleString()); row("Last seen", new Date(ch.last_seen).toLocaleString()); }
      body.appendChild(dl);
      if (v && v.url) { var a = h("a", "btn small", "Open original"); a.href = v.url; a.target = "_blank"; a.rel = "noopener noreferrer"; body.appendChild(a); }
    }).catch(function (err) { clear(body); body.appendChild(h("p", "muted", err.message)); });
  }

  /* ---------- interests ---------- */
  function renderInterests() {
    return api("/api/caretaker/interests").then(function (d) {
      var box = clear($("ad-interests"));
      if (d.message) box.appendChild(C.empty(d.message));
      if (d.insights.length) { var ul = h("ul", "ad-insights"); d.insights.forEach(function (i) { var li = h("li"); li.appendChild(h("span", "ad-pill ad-pill--" + i.kind, STATUS[i.kind] || i.kind)); li.appendChild(h("p", null, i.text)); ul.appendChild(li); }); box.appendChild(ul); }
      var list = d.interests.filter(function (i) { return i.sessions > 0 || i.likes || i.favorites; }).slice(0, 8);
      if (list.length) {
        var grid = h("div", "ad-interest-grid");
        list.forEach(function (i) {
          var c = h("article", "ad-interest" + (i.qualified ? " is-possible" : "")); c.style.setProperty("--c", i.color);
          var top = h("div", "ad-interest-top"); top.append(h("strong", null, i.label), h("span", "ad-pill ad-pill--" + i.status, i.qualified ? (STATUS[i.status] || i.status) : "Exploring"));
          c.append(top, h("p", "small", i.evidence));
          var lv = h("div", "ad-level"); lv.setAttribute("aria-label", "Emphasis in My World: level " + i.level + " of 3");
          for (var k = 1; k <= 3; k++) lv.appendChild(h("i", k <= i.level ? "on" : ""));
          c.append(lv, h("small", "muted", i.qualified ? "Emphasised in My World (level " + i.level + ")" : "Not yet repeated enough to shape the world"));
          grid.appendChild(c);
        }); box.appendChild(grid);
      }
      box.appendChild(h("p", "ad-disclaimer", d.disclaimer));
    }).catch(function () { fail("ad-interests"); });
  }

  /* ---------- orchestration ---------- */
  function setLive(txt) { $("ad-live-text").textContent = txt; }
  function setDay(day) { state.day = day; $("ad-day").value = day; loadAll(true); $("ad-graphs").scrollIntoView({ block: "start" }); }
  function loadSummary() {
    return api("/api/caretaker/activity/summary", rangeParams()).then(function (d) {
      state.summary = d; $("ad-day").min = d.range.earliest; $("ad-day").max = d.range.end; $("ad-day").value = d.range.focus_day;
      renderStats(d); renderGraphs(d); renderTrends(d); renderRankings(d); fillCategories(d);
      var ul = $("ad-formulas"); if (!ul.children.length) d.formulas.forEach(function (f) { var li = h("li"); li.append(h("strong", null, f.name + ": "), document.createTextNode(f.formula)); ul.appendChild(li); });
      setLive(d.has_data ? "Updated " + new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }) : "Waiting for the first activity");
    }).catch(function (e) { ["ad-stats"].forEach(function (id) { fail(id, e.message); }); setLive("Could not refresh"); });
  }
  function loadAll(keepFilters) {
    return loadSummary().then(function () { return Promise.all([renderFeed(), renderTimeline(), renderInterests(), keepFilters ? null : renderHistory(), renderPeriods(activeGroup)]); });
  }
  var activeGroup = "week";

  // range chips
  $("ad-ranges").addEventListener("click", function (e) {
    var b = e.target.closest("button[data-range]"); if (!b) return;
    state.range = b.dataset.range; state.day = "";
    $("ad-ranges").querySelectorAll("button").forEach(function (x) { x.classList.toggle("is-active", x === b); x.setAttribute("aria-pressed", x === b ? "true" : "false"); });
    loadAll(true);
  });
  $("ad-apply").addEventListener("click", function () {
    if (!$("ad-start").value || !$("ad-end").value) return;
    state.range = "custom"; state.start = $("ad-start").value; state.end = $("ad-end").value; state.day = "";
    $("ad-ranges").querySelectorAll("button").forEach(function (x) { x.classList.remove("is-active"); x.setAttribute("aria-pressed", "false"); });
    loadAll(true);
  });
  $("ad-day").addEventListener("change", function () { state.day = this.value; loadSummary().then(renderTimeline); });
  var childSel = $("ad-child"); if (childSel) childSel.addEventListener("change", function () { location.href = "/caretaker/activity?child=" + encodeURIComponent(this.value); });

  // history filters
  var debounce = null;
  function refilter() { state.page = 1; renderHistory(); }
  $("ad-type-chips").addEventListener("click", function (e) {
    var b = e.target.closest("button[data-type]"); if (!b) return; state.type = b.dataset.type;
    $("ad-type-chips").querySelectorAll("button").forEach(function (x) { var on = x === b; x.classList.toggle("is-on", on); x.setAttribute("aria-pressed", on ? "true" : "false"); }); refilter();
  });
  $("ad-q").addEventListener("input", function () { clearTimeout(debounce); var v = this.value.trim(); debounce = setTimeout(function () { state.q = v; refilter(); }, 350); });
  $("ad-action").addEventListener("change", function () { state.action = this.value; refilter(); });
  $("ad-category").addEventListener("change", function () { state.category = this.value; refilter(); });
  $("ad-h-start").addEventListener("change", function () { state.hs = this.value; refilter(); });
  $("ad-h-end").addEventListener("change", function () { state.he = this.value; refilter(); });
  $("ad-filters").addEventListener("submit", function (e) { e.preventDefault(); });
  $("ad-filters").addEventListener("reset", function () { setTimeout(function () {
    state.type = state.action = state.category = state.q = state.hs = state.he = "";
    $("ad-type-chips").querySelectorAll("button").forEach(function (x) { var on = x.dataset.type === ""; x.classList.toggle("is-on", on); x.setAttribute("aria-pressed", on ? "true" : "false"); }); refilter(); }, 0); });
  $("ad-quick").addEventListener("click", function (e) {
    var b = e.target.closest("button[data-quick]"); if (!b) return;
    var now = new Date(), iso = function (d) { return new Date(d.getTime() - d.getTimezoneOffset() * 60000).toISOString().slice(0, 10); };
    var start = new Date(now); activeGroup = b.dataset.quick;
    if (b.dataset.quick === "week") start.setDate(now.getDate() - ((now.getDay() + 6) % 7)); else if (b.dataset.quick === "month") start.setDate(1);
    state.hs = iso(start); state.he = iso(now); $("ad-h-start").value = state.hs; $("ad-h-end").value = state.he;
    refilter(); renderPeriods(b.dataset.quick);
  });
  $("ad-dialog-close").addEventListener("click", function () { $("ad-dialog").close(); });
  $("ad-dialog").addEventListener("close", function () { clear($("ad-dialog-body")); });          /* removing the iframe stops any playing media */
  $("ad-dialog").addEventListener("click", function (e) { if (e.target === this) this.close(); });

  loadAll(false);
  setInterval(function () { if (!document.hidden && !$("ad-dialog").open) { loadSummary().then(function () { return Promise.all([renderFeed(), renderTimeline()]); }); } }, 45000);
})();
