/* MyMind — My World room. Two clearly separate sections:
   WATCHED      what this child really opened here (sent by the server in #mwr-data, newest first).
   RECOMMENDED  new things, loaded from the existing safety-filtered endpoints (/api/pictures|videos|music|shots), which already apply
                the caregiver's blocklist, age rules and "not for me" choices. Anything already watched is not repeated.
   Nothing here rushes the child: no timers, no counters, an empty section just says it is fine to look around. */
(function () {
  'use strict';
  var MM = window.MyMind, root = document.getElementById('mwr');
  if (!MM || !root) return;
  var data = JSON.parse(document.getElementById('mwr-data').textContent || '{}');
  var ENDPOINT = { pictures: '/api/pictures', videos: '/api/videos', music: '/api/music', shots: '/api/shots' };
  var seed = Math.floor(Math.random() * 2147483647);

  // ---- Watched ----
  var wGrid = document.getElementById('mwr-watched'), wEmpty = document.getElementById('mwr-watched-empty');
  var watched = data.watched || [], seen = {};
  watched.forEach(function (it) {
    seen[it.id] = true;
    var card = MM.card(it, { hideOnDislike: false });
    var tag = MM.el('span', 'mwr-watched-tag', 'Watched');
    tag.insertBefore(svgCheck(), tag.firstChild);
    card.classList.add('is-watched'); card.appendChild(tag); wGrid.appendChild(card);
  });
  wEmpty.hidden = watched.length > 0;
  function svgCheck() {
    var s = document.createElementNS('http://www.w3.org/2000/svg', 'svg'), u = document.createElementNS('http://www.w3.org/2000/svg', 'use');
    s.setAttribute('class', 'ic sm'); s.setAttribute('aria-hidden', 'true'); u.setAttribute('href', '#i-check'); s.appendChild(u); return s;
  }

  // ---- Recommended ----
  var grid = document.getElementById('mwr-grid');
  if (!grid) return;
  var empty = document.getElementById('mwr-empty'), more = document.getElementById('mwr-more');
  var state = { kind: (data.kinds || [])[0], q: '', page: 1, loading: false, done: false, shown: {} };

  function pressed(group, attr, value) {
    if (!group) return;
    group.querySelectorAll('button').forEach(function (b) { b.setAttribute('aria-pressed', String(b.getAttribute(attr) === value)); });
  }
  function reset() { state.page = 1; state.done = false; state.shown = {}; grid.replaceChildren(); empty.hidden = true; more.hidden = true; }
  function load(tries) {
    if (state.loading || state.done || !state.kind) return;
    state.loading = true; more.disabled = true;
    if (state.page === 1) grid.replaceChildren(MM.skeletons(2));
    var p = new URLSearchParams({ page: state.page, seed: seed });
    if (data.cat) p.set('category', data.cat);
    if (state.q) p.set('q', state.q);
    var kind = state.kind, qNow = state.q;
    return MM.api(ENDPOINT[kind] + '?' + p.toString()).then(function (d) {
      if (kind !== state.kind || qNow !== state.q) { state.loading = false; return; }        // the child switched while this was loading
      var items = (d && d.items) || [];
      if (state.page === 1) grid.replaceChildren();
      var added = 0;
      items.forEach(function (i) {
        if (state.shown[i.id] || seen[i.id]) return;
        state.shown[i.id] = true; added++;
        grid.appendChild(MM.card(i, { hideOnDislike: false }));
      });
      if (!items.length || d.more === false) state.done = true;
      state.page++; state.loading = false;
      if (!added && !state.done && (tries || 0) < 3) return load((tries || 0) + 1);
      empty.hidden = grid.children.length > 0; more.hidden = state.done; more.disabled = false;
    }).catch(function (e) {
      state.loading = false; state.done = true; grid.replaceChildren();
      empty.textContent = (e && e.message) || empty.textContent; empty.hidden = false; more.hidden = true;
    });
  }

  var kinds = document.getElementById('mwr-kinds'), topics = document.getElementById('mwr-topics');
  if (kinds) kinds.addEventListener('click', function (e) {
    var b = e.target.closest('button[data-kind]'); if (!b || b.getAttribute('data-kind') === state.kind) return;
    state.kind = b.getAttribute('data-kind'); pressed(kinds, 'data-kind', state.kind); reset(); load(0);
  });
  if (topics) topics.addEventListener('click', function (e) {
    var b = e.target.closest('button[data-q]'); if (!b || b.getAttribute('data-q') === state.q) return;
    state.q = b.getAttribute('data-q'); pressed(topics, 'data-q', state.q); reset(); load(0);
  });
  more.addEventListener('click', function () { load(0); });
  load(0);
})();
