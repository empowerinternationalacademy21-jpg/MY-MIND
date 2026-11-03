/* Home "Feed": story circles pick a topic, then an endless list of posts. Each post = one big picture/video card
   with actions, followed by a row of mini cards ("More to explore"). The next page loads automatically as the child
   scrolls; there is no "show more" button. Errors retry quietly a few times. */
(function () {
  const MM = window.MyMind, el = MM.el;
  const host = document.getElementById("sections");

  // loading indicator (reuses the existing skeleton look, so no new CSS is needed) + invisible scroll sentinel
  const spinner = el("div", "skeleton fd-skel"); spinner.setAttribute("aria-hidden", "true"); spinner.style.display = "none";
  const endNote = el("p", "center muted", "You have seen everything for now. Pick another topic above."); endNote.hidden = true;
  const sentinel = el("div", "sentinel"); sentinel.setAttribute("aria-hidden", "true"); sentinel.style.height = "1px";
  host.insertAdjacentElement("afterend", spinner);
  spinner.insertAdjacentElement("afterend", endNote);
  endNote.insertAdjacentElement("afterend", sentinel);

  let page = 1, cat = "", loading = false, done = false, gen = 0, failures = 0;
  const seen = new Set();                            // content ids already on screen, so nothing repeats
  const KIND = { picture: "Picture", video: "Video", short: "Short", song: "Song" };
  const VERB = { picture: "View", video: "Watch", short: "Watch", song: "Play" };
  const fmt = (s) => { if (!s) return ""; const m = Math.floor(s / 60), r = s % 60; return m + ":" + String(r).padStart(2, "0"); };
  const showSpinner = (on) => { spinner.style.display = on ? "" : "none"; };

  function act(icon, label, pressed, fn, cls, iconOnly) {
    const b = el("button", "act " + (cls || "")); b.type = "button"; b.setAttribute("aria-label", label); b.title = label;
    b.appendChild(MM.icon(icon)); if (!iconOnly) b.appendChild(el("span", null, label));
    if (pressed !== undefined) b.setAttribute("aria-pressed", pressed ? "true" : "false");
    b.onclick = async (e) => { e.stopPropagation(); try { await fn(b); } catch (err) { MM.toast(err.message); } };
    return b;
  }

  function post(s, item) {
    const art = el("article", "post");
    const head = el("div", "post__head"); const av = el("span", "post__avatar"); av.appendChild(MM.icon(s.icon));
    const who = el("div"); who.append(el("p", "post__name", s.label), el("span", "post__handle", s.reason));
    head.append(av, who);

    const media = el("button", "post__media"); media.type = "button"; media.setAttribute("aria-label", "Open " + item.title);
    if (item.thumb) { const img = el("img"); img.src = item.thumb; img.alt = ""; img.loading = "lazy"; media.appendChild(img); }
    if (item.type !== "picture") {
      const p = el("span", "post__play"); p.appendChild(MM.icon("play", "lg")); media.appendChild(p);
      if (item.attribution.duration) media.appendChild(el("span", "post__dur", fmt(item.attribution.duration)));
    }
    if (item.demo) media.appendChild(el("span", "badge", "Demo"));
    media.onclick = () => MM.open(item);

    const actions = el("div", "post__actions");
    const like = act("thumbs-up", "Like", item.reaction === "like", async (b) => {
      await MM.react(item, "like"); b.setAttribute("aria-pressed", "true"); dis.setAttribute("aria-pressed", "false"); MM.toast("Nice choice!");
    }, "like");
    const fav = act("heart", "Favourite", item.favorite, async (b) => {
      const r = await MM.api("/api/favorite", { json: { content_id: item.id } });
      b.setAttribute("aria-pressed", r.favorite); MM.toast(r.favorite ? "Added to favorites" : "Removed from favorites");
    }, "heart");
    const dis = act("thumbs-down", "Not for me", item.reaction === "dislike", async (b) => {
      await MM.react(item, "dislike"); b.setAttribute("aria-pressed", "true"); like.setAttribute("aria-pressed", "false");
      art.style.opacity = ".45"; MM.toast("Okay, we'll show less like this.");
    }, "", true);
    const moreLike = el("a", "act more"); moreLike.href = "/explore/" + item.id; moreLike.setAttribute("aria-label", "More like this");
    moreLike.append(MM.icon("search"), el("span", null, "More like this")); moreLike.addEventListener("click", () => MM.react(item, "explore"));
    actions.append(like, fav, moreLike, dis, el("span", "post__kind", KIND[item.type] || ""));

    art.append(head, media, actions);
    return art;
  }

  function mini(item) {
    const c = el("article", "mini");
    const pic = el("button", "mini__pic"); pic.type = "button"; pic.setAttribute("aria-label", "Open " + item.title);
    if (item.thumb) { const img = el("img"); img.src = item.thumb; img.alt = ""; img.loading = "lazy"; pic.appendChild(img); }
    pic.onclick = () => MM.open(item);
    const foot = el("div", "mini__foot");
    const go = el("button", "pillbtn", VERB[item.type] || "Open"); go.type = "button"; go.onclick = () => MM.open(item);
    foot.append(MM.favButton(item, "tool"), go);
    c.append(pic, el("h4", "mini__title", item.title), el("p", "mini__sub", item.attribution.artist || item.attribution.channel || item.category_label), foot);
    return c;
  }

  function section(s, items) {
    const wrap = document.createElement("section"); wrap.dataset.label = s.label;
    const hero = items.find((i) => i.type === "picture") || items[0];
    const rest = items.filter((i) => i !== hero);
    wrap.appendChild(post(s, hero));
    if (rest.length) {
      const row = el("div", "hrow"); row.append(...rest.map(mini));
      wrap.append(el("h3", "post__more", "More to explore"), row);
    }
    return wrap;
  }

  async function load(append, tries = 0) {
    if (append && (loading || done)) return;
    const my = append ? gen : ++gen;                 // choosing another topic cancels whatever is still loading
    loading = true;
    showSpinner(true);
    if (!append) {
      host.replaceChildren(el("div", "skeleton fd-skel"), el("div", "skeleton fd-skel"));
      page = 1; done = false; failures = 0; seen.clear(); endNote.hidden = true;
    }
    let added = 0;
    try {
      const d = await MM.api("/api/feed?page=" + page + (cat ? "&category=" + encodeURIComponent(cat) : ""));
      if (my !== gen) return;
      if (!append) host.replaceChildren();
      MM.notice(host.parentElement, d.notice);
      d.sections.forEach((s) => {
        const fresh = s.items.filter((i) => !seen.has(i.id)); fresh.forEach((i) => seen.add(i.id));
        if (fresh.length) { host.appendChild(section(s, fresh)); added++; }
      });
      if (d.more === false) done = true;
      else if (!added && tries < 3) { page++; loading = false; return load(true, tries + 1); }   // only repeats: try the next page
      if (!host.children.length) host.appendChild(el("div", "empty", "Nothing new right now. Please try again in a moment."));
    } catch (e) {
      if (my !== gen) return;
      loading = false;
      if (!append) { host.replaceChildren(el("div", "empty", e.message)); showSpinner(false); return; }
      page = Math.max(1, page - 1);
      if (++failures <= 3) setTimeout(endless.check, 3000 * failures);   // quiet retry, no button needed
      else { showSpinner(false); MM.toast(e.message); }
      return;
    }
    failures = 0;
    loading = false;
    showSpinner(!done);
    endNote.hidden = !(done && host.children.length);
    if (added && !done) setTimeout(endless.check, 50);
  }
  const next = () => { if (loading || done) return; page++; return load(true); };
  const endless = MM.endless(sentinel, next);

  const stories = document.querySelectorAll(".story[data-cat]");
  stories.forEach((c) => c.addEventListener("click", () => {
    stories.forEach((x) => x.setAttribute("aria-pressed", "false")); c.setAttribute("aria-pressed", "true");
    cat = c.dataset.cat; load(false);
  }));
  document.getElementById("search").addEventListener("submit", (e) => { e.preventDefault(); const q = document.getElementById("q").value.trim(); if (q) location.href = "/pictures?q=" + encodeURIComponent(q); });

  async function strip(id, url) {                    // favourites / recent: shown only when there is something in them
    const g = document.getElementById(id), wrap = document.getElementById(id + "-wrap");
    try {
      const d = await MM.api(url);
      if (d.items.length) { g.replaceChildren(...d.items.map((i) => MM.card(i, { hideOnDislike: false }))); wrap.hidden = false; }
    } catch (e) { }
  }
  load(false);
  strip("favs", "/api/favorites");
  strip("recent", "/api/recent");
})();