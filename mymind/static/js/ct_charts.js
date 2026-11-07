/* Small dependency-free chart helpers for the caretaker Activity dashboard (plain SVG, responsive, keyboard/screen-reader friendly).
   Every label is written with textContent, never innerHTML, because titles come from external content (YouTube, Spotify, Pexels). */
(function () {
  "use strict";
  var NS = "http://www.w3.org/2000/svg";
  function s(tag, attrs, text) {
    var n = document.createElementNS(NS, tag);
    if (attrs) for (var k in attrs) n.setAttribute(k, attrs[k]);
    if (text != null) n.textContent = text;
    return n;
  }
  function h(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text != null) n.textContent = text;
    return n;
  }
  function fmtMin(m) {
    if (!m || m <= 0) return "0 min";
    if (m < 1) return Math.max(1, Math.round(m * 60)) + " sec";
    if (m < 10) return (Math.round(m * 10) / 10) + " min";
    if (m < 120) return Math.round(m) + " min";
    return (Math.round(m / 6) / 10) + " h";
  }
  function niceMax(v) {
    if (v <= 0) return 1;
    var p = Math.pow(10, Math.floor(Math.log10(v))), f = v / p;
    return (f <= 1 ? 1 : f <= 2 ? 2 : f <= 5 ? 5 : 10) * p;
  }
  function wrap(label) {                       /* every chart sits in a figure with a text summary for assistive tech */
    var fig = h("figure", "adc");
    fig.setAttribute("role", "group");
    fig.setAttribute("aria-label", label);
    return fig;
  }
  function tipLayer(fig) {
    var tip = h("div", "adc-tip"); tip.hidden = true; tip.setAttribute("role", "status"); fig.appendChild(tip);
    return {
      show: function (target, text) {
        tip.textContent = text; tip.hidden = false;
        var f = fig.getBoundingClientRect(), r = target.getBoundingClientRect();
        tip.style.left = Math.max(4, Math.min(f.width - tip.offsetWidth - 4, r.left - f.left + r.width / 2 - tip.offsetWidth / 2)) + "px";
        tip.style.top = Math.max(0, r.top - f.top - tip.offsetHeight - 6) + "px";
      },
      hide: function () { tip.hidden = true; }
    };
  }
  function hover(el, tip, text) {
    el.setAttribute("tabindex", "0"); el.setAttribute("aria-label", text);
    el.addEventListener("mouseenter", function () { tip.show(el, text); });
    el.addEventListener("focus", function () { tip.show(el, text); });
    el.addEventListener("mouseleave", tip.hide);
    el.addEventListener("blur", tip.hide);
    el.addEventListener("click", function () { tip.show(el, text); });      /* touch screens */
  }
  function legend(items) {
    var ul = h("ul", "adc-legend");
    items.forEach(function (it) {
      var li = h("li"), dot = h("i"); dot.style.background = it.color;
      li.append(dot, h("span", null, it.label));
      ul.appendChild(li);
    });
    return ul;
  }
  function empty(text) { return h("p", "adc-empty", text); }

  /* ---- vertical columns (optionally stacked). opts: {labels, series:[{name,color,values}], stacked, fmt, label, onSelect, highlight} ---- */
  function columns(opts) {
    var labels = opts.labels, series = opts.series, W = 640, H = 220, L = 38, B = 28, T = 10, R = 6;
    var fmt = opts.fmt || fmtMin, fig = wrap(opts.label || "Chart"), tip = tipLayer(fig);
    var totals = labels.map(function (_, i) { return opts.stacked ? series.reduce(function (a, x) { return a + (x.values[i] || 0); }, 0) : Math.max.apply(null, series.map(function (x) { return x.values[i] || 0; })); });
    var max = niceMax(Math.max.apply(null, totals.concat([0])));
    var svg = s("svg", { viewBox: "0 0 " + W + " " + H, class: "adc-svg", role: "img", "aria-label": opts.label || "Chart" });
    [0, .25, .5, .75, 1].forEach(function (f) {
      var y = T + (H - T - B) * (1 - f);
      svg.appendChild(s("line", { x1: L, x2: W - R, y1: y, y2: y, class: "adc-grid" }));
      svg.appendChild(s("text", { x: L - 6, y: y + 4, class: "adc-axis", "text-anchor": "end" }, fmt(max * f).replace(" min", "")));
    });
    var n = labels.length, slot = (W - L - R) / n, bw = Math.max(3, Math.min(34, slot * .66));
    var step = Math.ceil(n / 8);
    labels.forEach(function (lab, i) {
      var x = L + slot * i + (slot - bw) / 2, y0 = H - B, acc = 0;
      var g = s("g", { class: "adc-col" + (opts.highlight === i ? " is-hi" : "") });
      var parts = [];
      series.forEach(function (ser) {
        var v = ser.values[i] || 0; if (v <= 0) return;
        var bh = (H - T - B) * (v / max), yy = opts.stacked ? y0 - (acc / max) * (H - T - B) - bh : y0 - bh;
        var bwEach = opts.stacked ? bw : bw / series.length, xx = opts.stacked ? x : x + series.indexOf(ser) * bwEach;
        g.appendChild(s("rect", { x: xx, y: yy, width: Math.max(2, bwEach), height: Math.max(1, bh), rx: 3, fill: ser.color }));
        parts.push(ser.name + ": " + fmt(v)); acc += opts.stacked ? v : 0;
      });
      var hit = s("rect", { x: L + slot * i, y: T, width: slot, height: H - T - B, fill: "transparent", class: "adc-hit" });
      var text = lab + (parts.length ? " · " + parts.join(", ") : " · none");
      hover(hit, tip, text);
      if (opts.onSelect) { hit.style.cursor = "pointer"; hit.addEventListener("click", function () { opts.onSelect(i); }); hit.addEventListener("keydown", function (e) { if (e.key === "Enter") opts.onSelect(i); }); }
      g.appendChild(hit); svg.appendChild(g);
      if (i % step === 0) svg.appendChild(s("text", { x: x + bw / 2, y: H - 8, class: "adc-axis", "text-anchor": "middle" }, (opts.shortLabels || labels)[i]));
    });
    fig.appendChild(svg);
    if (series.length > 1 || opts.showLegend) fig.appendChild(legend(series.map(function (x) { return { label: x.name, color: x.color }; })));
    return fig;
  }

  /* ---- smooth-ish lines. opts: {labels, series:[{name,color,values}], fmt, label} ---- */
  function lines(opts) {
    var labels = opts.labels, series = opts.series, W = 640, H = 220, L = 38, B = 28, T = 12, R = 10;
    var fmt = opts.fmt || fmtMin, fig = wrap(opts.label || "Chart"), tip = tipLayer(fig);
    var max = niceMax(Math.max.apply(null, [0].concat.apply([], series.map(function (x) { return x.values; }))));
    var svg = s("svg", { viewBox: "0 0 " + W + " " + H, class: "adc-svg", role: "img", "aria-label": opts.label || "Chart" });
    [0, .5, 1].forEach(function (f) {
      var y = T + (H - T - B) * (1 - f);
      svg.appendChild(s("line", { x1: L, x2: W - R, y1: y, y2: y, class: "adc-grid" }));
      svg.appendChild(s("text", { x: L - 6, y: y + 4, class: "adc-axis", "text-anchor": "end" }, fmt(max * f).replace(" min", "")));
    });
    var n = labels.length, X = function (i) { return n === 1 ? (L + W - R) / 2 : L + (W - L - R) * i / (n - 1); }, Y = function (v) { return T + (H - T - B) * (1 - v / max); };
    series.forEach(function (ser) {
      var d = ser.values.map(function (v, i) { return (i ? "L" : "M") + X(i).toFixed(1) + "," + Y(v).toFixed(1); }).join(" ");
      svg.appendChild(s("path", { d: d, fill: "none", stroke: ser.color, "stroke-width": 2.6, "stroke-linecap": "round", "stroke-linejoin": "round" }));
      ser.values.forEach(function (v, i) {
        var dot = s("circle", { cx: X(i), cy: Y(v), r: 4.5, fill: ser.color, class: "adc-dot" });
        hover(dot, tip, ser.name + " · " + labels[i] + " · " + fmt(v)); svg.appendChild(dot);
      });
    });
    var step = Math.ceil(n / 8);
    labels.forEach(function (lab, i) { if (i % step === 0) svg.appendChild(s("text", { x: X(i), y: H - 8, class: "adc-axis", "text-anchor": "middle" }, (opts.shortLabels || labels)[i])); });
    fig.appendChild(svg);
    fig.appendChild(legend(series.map(function (x) { return { label: x.name, color: x.color }; })));
    return fig;
  }

  /* ---- horizontal bars. opts: {items:[{label,value,color,sub,thumb}], fmt, max, label} ---- */
  function hbars(opts) {
    var fig = wrap(opts.label || "Chart"), fmt = opts.fmt || fmtMin;
    var max = opts.max || Math.max.apply(null, opts.items.map(function (i) { return i.value; }).concat([0.0001]));
    var list = h("ul", "adc-hbars");
    opts.items.forEach(function (it) {
      var li = h("li");
      if (it.thumb) { var img = h("img", "adc-thumb"); img.src = it.thumb; img.alt = ""; img.loading = "lazy"; img.referrerPolicy = "no-referrer"; li.appendChild(img); }
      var body = h("div", "adc-hb"), top = h("div", "adc-hb-top");
      top.append(h("span", "adc-hb-label", it.label), h("b", null, it.text || fmt(it.value)));
      var track = h("div", "adc-track"), fill = h("i"); fill.style.width = Math.max(2, it.value / max * 100) + "%"; fill.style.background = it.color || "var(--ct-orange)";
      track.appendChild(fill); body.append(top, track);
      if (it.sub) body.appendChild(h("small", null, it.sub));
      li.appendChild(body); list.appendChild(li);
    });
    fig.appendChild(list); return fig;
  }

  /* ---- doughnut. opts: {items:[{label,value,color}], center, sub, label, fmt} ---- */
  function doughnut(opts) {
    var fig = wrap(opts.label || "Chart"), tip = tipLayer(fig), fmt = opts.fmt || fmtMin;
    var total = opts.items.reduce(function (a, i) { return a + i.value; }, 0);
    var box = h("div", "adc-donut"), svg = s("svg", { viewBox: "0 0 120 120", class: "adc-svg adc-svg--donut", role: "img", "aria-label": opts.label || "Chart" });
    var R = 46, C = 2 * Math.PI * R, off = 0;
    svg.appendChild(s("circle", { cx: 60, cy: 60, r: R, fill: "none", class: "adc-donut-track", "stroke-width": 16 }));
    opts.items.forEach(function (it) {
      var len = total ? it.value / total * C : 0; if (len <= 0) return;
      var seg = s("circle", { cx: 60, cy: 60, r: R, fill: "none", stroke: it.color, "stroke-width": 16, "stroke-dasharray": len.toFixed(2) + " " + (C - len).toFixed(2),
        "stroke-dashoffset": (-off).toFixed(2), transform: "rotate(-90 60 60)", class: "adc-seg" });
      hover(seg, tip, it.label + " · " + fmt(it.value) + " · " + Math.round(it.value / total * 100) + "%"); svg.appendChild(seg); off += len;
    });
    var c = h("div", "adc-donut-centre"); c.append(h("strong", null, opts.center || ""), h("small", null, opts.sub || ""));
    box.append(svg, c); fig.appendChild(box);
    var ul = h("ul", "adc-legend adc-legend--col");
    opts.items.forEach(function (it) {
      var li = h("li"), dot = h("i"); dot.style.background = it.color;
      li.append(dot, h("span", null, it.label), h("b", null, total ? Math.round(it.value / total * 100) + "%" : "0%")); ul.appendChild(li);
    });
    fig.appendChild(ul); return fig;
  }

  /* ---- 24 hour timeline strip: blocks for engaged sessions. opts: {events:[{hour,time,seconds,color,label}]} ---- */
  function dayStrip(opts) {
    var fig = wrap(opts.label || "Timeline of the day"), strip = h("div", "adc-strip"), tip = tipLayer(fig);
    for (var hr = 0; hr < 24; hr += 6) { var tick = h("span", "adc-strip-tick", String(hr).padStart(2, "0") + ":00"); tick.style.left = (hr / 24 * 100) + "%"; strip.appendChild(tick); }
    opts.events.forEach(function (ev) {
      var parts = ev.time.split(":"), start = (+parts[0] * 60 + +parts[1]) / 1440, width = Math.max(.006, (ev.seconds || 20) / 86400);
      var b = h("button", "adc-block"); b.type = "button"; b.style.left = (start * 100) + "%"; b.style.width = (width * 100) + "%"; b.style.background = ev.color;
      hover(b, tip, ev.time + " · " + ev.label); strip.appendChild(b);
    });
    fig.appendChild(strip); return fig;
  }

  window.CTCharts = { columns: columns, lines: lines, hbars: hbars, doughnut: doughnut, dayStrip: dayStrip, fmtMin: fmtMin, empty: empty, el: h };
})();
