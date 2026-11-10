/* MyMind — child topic page. One page per topic; four sections: Pictures, Music, Videos, Shorts.
   Each section asks the existing, safety-filtered endpoints (/api/pictures, /api/music, /api/videos, /api/shots)
   for that topic only (?category=<topic>), and uses the same cards as the rest of the app
   (same open / like / favourite behaviour and the same caregiver controls).
   Sections load as they come into view, so a visit does not use video/music search quota the child never scrolls to. */
(function () {
  'use strict';
  var MM = window.MyMind, el = MM.el;
  var root = document.getElementById('topic');
  if (!root) return;
  var cat = root.getAttribute('data-cat');
  var seed = Math.floor(Math.random() * 2147483647);       // a new number each visit = fresh picks each visit

  var KINDS = { pictures: '/api/pictures', music: '/api/music', videos: '/api/videos', shots: '/api/shots' };
  var started = {};

  function section(kind) {
    var box = document.getElementById('sec-' + kind);
    if (!box || box.hidden) return null;
    var grid = document.getElementById('grid-' + kind);
    var empty = document.getElementById('empty-' + kind);
    var more = document.getElementById('more-' + kind);
    var page = 1, loading = false, done = false, seen = {};

    function finish() { more.hidden = done; more.disabled = false; }

    function load(tries) {
      if (loading || done) return;
      loading = true; more.disabled = true;
      if (page === 1) grid.replaceChildren(MM.skeletons(2));
      var params = new URLSearchParams({ category: cat, page: page, seed: seed });
      return MM.api(KINDS[kind] + '?' + params.toString()).then(function (d) {
        var items = (d && d.items) || [];
        if (page === 1) grid.replaceChildren();
        var added = 0;
        items.forEach(function (i) {
          if (seen[i.id]) return;
          seen[i.id] = true; added++;
          grid.appendChild(MM.card(i, { hideOnDislike: false }));
        });
        if (!items.length || d.more === false) done = true;
        page++;
        loading = false;
        if (!added && !done && (tries || 0) < 3) return load((tries || 0) + 1);   // only repeats: try the next page
        empty.hidden = grid.children.length > 0;
        finish();
      }).catch(function (e) {
        loading = false;
        if (page === 1) {
          grid.replaceChildren();
          if (kind === 'shots') { box.hidden = true; return; }                     // shorts switched off: just hide the section
          empty.textContent = e.message || empty.textContent; empty.hidden = false; done = true;
        } else { MM.toast(e.message); }
        finish();
      });
    }

    more.addEventListener('click', function () { load(0); });
    return { start: function () { if (!started[kind]) { started[kind] = true; load(0); } }, box: box };
  }

  var sections = Object.keys(KINDS).map(section).filter(Boolean);

  if ('IntersectionObserver' in window) {
    var io = new IntersectionObserver(function (entries) {
      entries.forEach(function (en) {
        if (!en.isIntersecting) return;
        io.unobserve(en.target);
        sections.forEach(function (s) { if (s.box === en.target) s.start(); });
      });
    }, { rootMargin: '500px 0px' });
    sections.forEach(function (s) { io.observe(s.box); });
  } else {
    sections.forEach(function (s) { s.start(); });
  }
})();
