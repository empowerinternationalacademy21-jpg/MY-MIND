/* MyMind — child "Favourites" page. Shows everything the child has saved with the heart button,
   using the same cards as the rest of the app (same open / like / favourite behaviour).
   Data comes from the existing GET /api/favorites endpoint (scoped to the signed-in child). */
(function () {
  'use strict';
  var MM = window.MyMind, el = MM.el;
  var grid = document.getElementById('grid');
  var empty = document.getElementById('empty');
  var filters = document.querySelectorAll('.chip[data-type]');
  var all = [], type = '';

  function show() {
    var items = all.filter(function (i) {
      if (!type) return true;
      if (type === 'video') return i.type === 'video' || i.type === 'short';
      return i.type === type;
    });
    grid.replaceChildren.apply(grid, items.map(function (i) { return MM.card(i, { hideOnDislike: false }); }));
    empty.hidden = items.length > 0;
    grid.hidden = items.length === 0;
  }

  filters.forEach(function (c) {
    c.addEventListener('click', function () {
      filters.forEach(function (x) { x.setAttribute('aria-pressed', 'false'); });
      c.setAttribute('aria-pressed', 'true');
      type = c.getAttribute('data-type') || '';
      show();
    });
  });

  grid.replaceChildren(MM.skeletons(4));
  MM.api('/api/favorites').then(function (d) {
    all = d.items || [];
    show();
  }).catch(function (e) {
    grid.replaceChildren(el('div', 'empty', e.message || 'Could not load your favourites.'));
  });
})();
