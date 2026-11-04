/* Music page: "For you" hero, endless list of songs, and a Now Playing sheet with previous / next.
   Songs play in the official embedded player (YouTube music videos: sound + picture; Spotify when available). */
(function () {
    const MM = window.MyMind, el = MM.el;
    const list = document.getElementById("grid"), more = document.getElementById("more"), hero = document.getElementById("hero");
    const form = document.getElementById("search"), q = document.getElementById("q");
    const chips = document.querySelectorAll(".chip[data-cat]");
    const dlg = document.getElementById("np"), npBody = dlg.querySelector(".np-body");

    let cat = "", page = 1, loading = false, done = false, gen = 0;
    let queue = [], current = -1, opened = 0;
    const seen = new Set();                                  // song ids already listed, so nothing repeats
    const fmt = (s) => { if (!s) return ""; const m = Math.floor(s / 60), r = s % 60; return m + ":" + String(r).padStart(2, "0"); };
    const sub = (item) => [item.attribution.artist || item.category_label, fmt(item.attribution.duration)].filter(Boolean).join(" · ");

    /* ---------- list ---------- */
    function row(item) {
        const r = el("article", "mu-row"); r.dataset.id = item.id;
        const art = el("button", "mu-art"); art.type = "button"; art.setAttribute("aria-label", "Play " + item.title);
        if (item.thumb) { const img = el("img"); img.src = item.thumb; img.alt = ""; img.loading = "lazy"; art.appendChild(img); }
        art.onclick = () => play(item);
        const txt = el("div", "mu-txt"); txt.append(el("p", "mu-title", item.title));
        const s = el("p", "mu-sub", sub(item));
        if (item.demo) { const d = el("span", "badge", "Demo"); d.style.marginLeft = ".35rem"; s.appendChild(d); }
        txt.appendChild(s); txt.onclick = () => play(item);
        const btn = el("button", "mu-play"); btn.type = "button"; btn.setAttribute("aria-label", "Play " + item.title);
        btn.appendChild(MM.icon("play")); btn.onclick = () => play(item);
        r.append(art, txt, MM.favButton(item, "tool"), btn);
        return r;
    }

    function renderHero(item) {
        if (!item) { hero.hidden = true; return; }
        hero.hidden = false; hero.classList.toggle("no-art", !item.thumb);
        const t = el("div");
        t.append(el("span", "mu-kicker", "For you"), el("h2", null, "Feel the beat"), el("p", null, "Songs picked from what you enjoy."));
        const b = el("button", "btn accent small"); b.type = "button"; b.append(MM.icon("play", "sm"), " Start listening"); b.onclick = () => play(item);
        t.appendChild(b);
        hero.replaceChildren(t);
        if (item.thumb) { const img = el("img", "art"); img.src = item.thumb; img.alt = ""; hero.appendChild(img); }
    }

    function markActive(item) {
        list.querySelectorAll(".mu-row").forEach((r) => r.classList.toggle("on", !!item && r.dataset.id === String(item.id)));
    }

    /* ---------- now playing sheet ---------- */
    function finishCurrent() {
        const cur = queue[current];
        if (cur && cur.embed && opened && Date.now() - opened > 10000) MM.react(cur, "watched");
        opened = 0;
    }

    function play(item) {
        finishCurrent();
        current = queue.indexOf(item); opened = Date.now();
        MM.react(item, "selected");
        markActive(item);
        renderSheet(item);
        if (!dlg.open) dlg.showModal();
    }

    async function playNext() {
        const previous = queue[current];
        if (current < queue.length - 1) {
            if (previous) MM.activity.log("next", null, previous.id);
            return play(queue[current + 1]);
        }
        if (loading) { MM.toast("Loading more songs…"); return; }
        if (done) { MM.toast("That's all for now."); return; }
        const before = queue.length; await next();
        if (queue.length > before) {
            if (previous) MM.activity.log("next", null, previous.id);
            play(queue[before]);
        } else MM.toast("No more songs right now.");
    }
    const playPrev = () => { if (current > 0) play(queue[current - 1]); else MM.toast("This is the first song."); };

    function renderSheet(item) {
        const top = el("div", "np-top");
        const close = el("button", "np-close", "×"); close.type = "button"; close.setAttribute("aria-label", "Close"); close.dataset.close = "";
        top.append(close, el("span", "np-label", "Now playing"), el("span", "np-spacer"));
        const parts = [top];
        const video = item.embed && item.provider === "youtube";          // a YouTube song is a music video: the player is the picture
        if (!video && item.thumb) { const img = el("img", "np-art"); img.src = item.thumb; img.alt = ""; parts.push(img); }
        const info = el("div", "np-info"); info.append(el("h2", null, item.title), el("p", null, item.attribution.artist || item.category_label));
        parts.push(info);
        if (item.embed) parts.push(MM.player(item));
        else parts.push(el("p", "notice", "This is a demo song, so there is nothing to play. Add API keys to hear real music."));

        const prev = el("button", "np-skip prev"); prev.type = "button"; prev.setAttribute("aria-label", "Previous song"); prev.appendChild(MM.icon("skip-forward")); prev.onclick = playPrev;
        const nxt = el("button", "np-skip"); nxt.type = "button"; nxt.setAttribute("aria-label", "Next song"); nxt.appendChild(MM.icon("skip-forward")); nxt.onclick = playNext;
        const ctrl = el("div", "np-ctrl"); ctrl.append(prev, MM.tools(item, null, { hideOnDislike: false, withFav: true }), nxt);
        parts.push(ctrl);

        if (item.url && item.provider !== "demo") {
            const a = el("a", "btn small", item.provider === "spotify" ? "Open in Spotify" : "Watch on YouTube");
            a.href = item.url; a.target = "_blank"; a.rel = "noopener noreferrer";
            const w = el("p", "np-link"); w.appendChild(a); parts.push(w);
        }
        npBody.replaceChildren(...parts);
    }
    dlg.addEventListener("close", () => { finishCurrent(); npBody.replaceChildren(); markActive(null); });   // closing stops the music

    /* ---------- loading (endless) ---------- */
    async function load(append, tries = 0) {
        if (append && (loading || done)) return;
        const my = append ? gen : ++gen;
        loading = true;
        if (!append) {
            list.replaceChildren(...Array.from({ length: 6 }, () => el("div", "skeleton mu-skel")));
            page = 1; done = false; seen.clear(); queue = []; current = -1; hero.hidden = true; more.hidden = false;
        }
        const params = new URLSearchParams({ page });
        if (cat) params.set("category", cat); if (q.value.trim()) params.set("q", q.value.trim());
        let added = 0;
        try {
            const d = await MM.api("/api/music?" + params);
            if (my !== gen) return;
            MM.notice(list.parentElement, d.notice);
            const fresh = d.items.filter((i) => !seen.has(i.id)); fresh.forEach((i) => seen.add(i.id));
            if (!append) list.replaceChildren();
            fresh.forEach((i) => { queue.push(i); list.appendChild(row(i)); added++; });
            if (!append) renderHero(fresh[0]);
            if (!d.items.length || d.more === false) done = true;
            else if (!fresh.length && tries < 3) { page++; loading = false; return load(true, tries + 1); }   // only repeats: try the next page
            if (!queue.length) list.appendChild(el("div", "empty", "No songs found. Try another topic."));
        } catch (e) {
            if (my !== gen) return;
            if (append) { page = Math.max(1, page - 1); MM.toast(e.message); } else list.replaceChildren(el("div", "empty", e.message));
            loading = false; return;                       // no automatic retry loop after an error; the button still works
        }
        loading = false;
        more.hidden = done;
        if (added && !done) setTimeout(endless.check, 50);
    }
    const next = () => { page++; return load(true); };
    const endless = MM.endless(more, next);

    chips.forEach((c) => c.addEventListener("click", () => {
        chips.forEach((x) => x.setAttribute("aria-pressed", "false")); c.setAttribute("aria-pressed", "true"); cat = c.dataset.cat; load(false);
    }));
    form.addEventListener("submit", (e) => { e.preventDefault(); load(false); });
    more.addEventListener("click", next);
    load(false);
})();