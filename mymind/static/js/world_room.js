/* MyMind — My World room. Panels:
   RECOMMENDED FOR YOU  new things, loaded from the existing safety-filtered endpoints (/api/pictures|videos|music|shots), which already apply
                        the caregiver's blocklist, age rules and "not for me" choices. Anything already watched is not repeated.
   YOUR WATCHED         what this child really opened here (sent by the server in #mwr-data, newest first), kept apart from the recommendations.
   MY FAVOURITES        (My Home only) the child's own favourites.
   Every thumbnail opens the same viewer, with the same like / favourite behaviour, as the rest of the app. Nothing rushes the child:
   no timers, no counters; an empty panel just says it is fine to look around. */
(function () {
  'use strict';
  var MM = window.MyMind, root = document.getElementById('mwr');
  if (!MM || !root) return;
  var el = MM.el;
  var data = JSON.parse(document.getElementById('mwr-data').textContent || '{}');
  var ENDPOINT = { pictures: '/api/pictures', videos: '/api/videos', music: '/api/music', shots: '/api/shots' };
  var seed = Math.floor(Math.random() * 2147483647);

  function dur(s) { s = Math.round(s || 0); return Math.floor(s / 60) + ':' + ('0' + (s % 60)).slice(-2); }
  function thumb(it, watchedTag) {
    var card = el('div', 'mwr-thumb' + (watchedTag ? ' is-watched' : ''));
    var b = el('button', 'mwr-thumb-media'); b.type = 'button'; b.setAttribute('aria-label', (it.type === 'picture' ? 'Open ' : 'Play ') + it.title);
    var src = it.type === 'picture' ? it.thumb : (MM.videoThumbnail ? MM.videoThumbnail(it) : it.thumb);
    if (src) { var img = el('img'); img.src = src; img.alt = ''; img.loading = 'lazy'; b.appendChild(img); }
    if (it.type !== 'picture') { var p = el('span', 'mwr-play'); p.appendChild(MM.icon('play', 'sm')); b.appendChild(p); }
    if (it.attribution && it.attribution.duration && it.type !== 'picture') b.appendChild(el('span', 'dur', dur(it.attribution.duration)));
    b.addEventListener('click', function () { MM.open(it); });
    card.appendChild(b);
    if (watchedTag) { var t = el('span', 'mwr-watched-tag'); t.appendChild(MM.icon('check', 'sm')); t.appendChild(document.createTextNode(' Watched')); card.appendChild(t); }
    card.appendChild(MM.favButton(it));
    card.appendChild(el('p', 'mwr-thumb-title', it.title));
    return card;
  }
  function expander(btn, panel) {            // "See All": the row becomes a wrapping grid
    if (!btn) return;
    btn.addEventListener('click', function () {
      var on = !panel.classList.contains('is-all');
      panel.classList.toggle('is-all', on); btn.setAttribute('aria-expanded', String(on)); btn.textContent = on ? 'Show less' : 'See All';
    });
  }

  // ---- Watched ----
  var wRow = document.getElementById('mwr-watched'), wEmpty = document.getElementById('mwr-watched-empty'), seen = {};
  var watched = data.watched || [];
  watched.forEach(function (it) { seen[it.id] = true; wRow.appendChild(thumb(it, true)); });
  wEmpty.hidden = watched.length > 0;
  expander(document.getElementById('mwr-watched-all'), document.getElementById('mwr-watched-panel'));

  // ---- My Home: favourites ----
  var fRow = document.getElementById('mwr-fav');
  if (fRow) {
    var favs = data.favorites || [];
    favs.forEach(function (it) { fRow.appendChild(thumb(it, false)); });
    document.getElementById('mwr-fav-empty').hidden = favs.length > 0;
  }

  // ---- Recommended ----
  var grid = document.getElementById('mwr-grid');
  if (!grid) return;
  var panel = document.getElementById('mwr-rec-panel'), empty = document.getElementById('mwr-empty'), more = document.getElementById('mwr-more');
  var state = { kind: (data.kinds || [])[0], q: data.q || '', page: 1, loading: false, done: false, shown: {} };
  var topicsQ = state.q;

  function pressed(group, attr, value) {
    if (!group) return;
    group.querySelectorAll('button').forEach(function (b) { b.setAttribute('aria-pressed', String(b.getAttribute(attr) === value)); });
  }
  function reset() { state.page = 1; state.done = false; state.shown = {}; grid.replaceChildren(); empty.hidden = true; more.hidden = true; }
  function load(tries) {
    if (state.loading || state.done || !state.kind) return;
    state.loading = true; more.disabled = true;
    if (state.page === 1) grid.replaceChildren(MM.skeletons(4));
    var p = new URLSearchParams({ page: state.page, seed: seed });
    if (data.cat) p.set('category', data.cat);
    if (state.q) p.set('q', state.q);
    var kind = state.kind, qNow = state.q;
    return MM.api(ENDPOINT[kind] + '?' + p.toString()).then(function (d) {
      if (kind !== state.kind || qNow !== state.q) { state.loading = false; return; }      // the child switched while this was loading
      var items = (d && d.items) || [];
      if (state.page === 1) grid.replaceChildren();
      var added = 0;
      items.forEach(function (i) {
        if (state.shown[i.id] || seen[i.id]) return;
        state.shown[i.id] = true; added++;
        grid.appendChild(thumb(i, false));
      });
      if (!items.length || d.more === false) state.done = true;
      state.page++; state.loading = false;
      if (!added && !state.done && (tries || 0) < 3) return load((tries || 0) + 1);
      empty.hidden = grid.children.length > 0; more.hidden = state.done || !panel.classList.contains('is-all'); more.disabled = false;
    }).catch(function (e) {
      state.loading = false; state.done = true; grid.replaceChildren();
      empty.textContent = (e && e.message) || empty.textContent; empty.hidden = false; more.hidden = true;
    });
  }

  var kinds = document.getElementById('mwr-kinds'), topics = document.getElementById('mwr-topics'), all = document.getElementById('mwr-rec-all');
  if (kinds) kinds.addEventListener('click', function (e) {
    var b = e.target.closest('button[data-kind]'); if (!b || b.getAttribute('data-kind') === state.kind) return;
    state.kind = b.getAttribute('data-kind'); pressed(kinds, 'data-kind', state.kind); reset(); load(0);
  });
  if (topics) topics.addEventListener('click', function (e) {
    var b = e.target.closest('button[data-q]'); if (!b || b.getAttribute('data-q') === state.q) return;
    state.q = b.getAttribute('data-q'); pressed(topics, 'data-q', state.q); reset(); load(0);
  });
  if (all) all.addEventListener('click', function () {
    var on = !panel.classList.contains('is-all');
    panel.classList.toggle('is-all', on); all.setAttribute('aria-expanded', String(on)); all.textContent = on ? 'Show less' : 'See All';
    more.hidden = !on || state.done;
    if (on && !state.done) load(0);          // expanding fetches the next page so there is more to see
  });
  more.addEventListener('click', function () { load(0); });
  load(0);
})();
