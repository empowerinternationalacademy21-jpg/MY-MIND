(function () {
  const MM = window.MyMind; const panel = document.getElementById("day-panel"); if (!panel) return;
  const row = (icon, title, sub, bg) => { const r = MM.el("div", "row"); const b = MM.el("span", "bub"); if (bg) b.style.background = bg; b.appendChild(MM.icon(icon));
    const g = MM.el("span", "grow", title); g.appendChild(MM.el("span", "sub", sub)); r.append(b, g); return r; };
  document.querySelectorAll("a.day[data-date]").forEach((a) => a.addEventListener("click", async (e) => {
    e.preventDefault(); const d = a.dataset.date; history.replaceState(null, "", a.href);
    document.querySelectorAll("a.day").forEach((x) => x.removeAttribute("aria-current")); a.setAttribute("aria-current", "date");
    try {
      const s = await MM.api("/api/journey/day/" + d); const rows = [];
      s.app_events.forEach((l) => rows.push(row("sparkles", l, "In the app")));
      s.recorded.forEach((r) => rows.push(row("notebook-pen", r.title, r.notes || "Recorded by caregiver", "#ffeccc")));
      if (!rows.length) { const r = MM.el("div", "row"); r.appendChild(MM.el("span", "grow muted", "Nothing recorded this day.")); rows.push(r); }
      panel.replaceChildren(...rows);
      const f = document.getElementById("activity_date"); if (f) f.value = d;
    } catch (err) { MM.toast(err.message); }
  }));
})();
