/* MyMind — Pictures page. Self-contained (no inline scripts, CSP-safe).
   Renders the masonry grid, topic filter, search, favourites strip,
   "Show more", and a full-size viewer. */
(function () {
  'use strict';

  /* ---------- CONFIG: adjust these if your backend differs ---------- */
  var CONFIG = {
    listEndpoint: '/api/pictures',          // GET ?q=&cat=&page=
    reactEndpoint: '/api/react',
    favoriteEndpoint: '/api/favorite',
    pageSize: 20,
    iconPrefix: '#i-'                       // must match ids in templates/_icons.html
  };

  var $ = function (id) { return document.getElementById(id); };
  var grid = $('grid'), skeleton = $('skeleton'), emptyMsg = $('empty'),
    moreBtn = $('more'), searchForm = $('search'), searchInput = $('q'),
    recentWrap = $('recent-wrap'), recent = $('recent');
  if (!grid) return;

  var state = { cat: '', q: '', page: 1, loading: false, hasMore: true, seen: {}, favs: {}, token: 0 };

  /* ---------- helpers ---------- */
  function csrfToken() {
    var m = document.querySelector('meta[name="csrf"]');
    if (m) return m.content;
    if (window.MyMind && window.MyMind.csrf) {
      return typeof window.MyMind.csrf === 'function' ? window.MyMind.csrf() : window.MyMind.csrf;
    }
    var c = document.cookie.match(/(?:^|;\s*)csrf_token=([^;]+)/);
    return c ? decodeURIComponent(c[1]) : '';
  }

  function toast(msg) {
    var box = $('toasts');
    if (!box) { box = document.createElement('div'); box.id = 'toasts'; document.body.appendChild(box); }
    var t = document.createElement('div');
    t.className = 'toast'; t.setAttribute('role', 'status'); t.textContent = msg;
    box.appendChild(t);
    setTimeout(function () { t.remove(); }, 3500);
  }

  function icon(name, cls) {
    var ns = 'http://www.w3.org/2000/svg';
    var svg = document.createElementNS(ns, 'svg');
    svg.setAttribute('class', 'ic' + (cls ? ' ' + cls : ''));
    svg.setAttribute('aria-hidden', 'true');
    var use = document.createElementNS(ns, 'use');
    use.setAttribute('href', CONFIG.iconPrefix + name);
    svg.appendChild(use);
    return svg;
  }

  function normalize(raw) {
    var url = raw.url || raw.image_url || raw.src || raw.large || '';
    return {
      id: String(raw.id != null ? raw.id : (raw.item_id != null ? raw.item_id : url)),
      url: url,
      thumb: raw.thumb || raw.thumbnail || raw.medium || url,
      alt: raw.alt || raw.title || 'Picture',
      credit: raw.credit || raw.photographer || '',
      creditUrl: raw.credit_url || raw.photographer_url || '',
      demo: !!(raw.demo || raw.is_demo),
      favorite: !!(raw.favorite || raw.is_favorite || raw.favourite),
      width: raw.width || 0,
      height: raw.height || 0,
      reason: raw.reason || ''
    };
  }

  function send(item, kind) {
    var favorite = kind === 'favorite' || kind === 'unfavorite';
    return fetch(favorite ? CONFIG.favoriteEndpoint : CONFIG.reactEndpoint, {
      method: 'POST',
      credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrfToken() },
      body: JSON.stringify(favorite
        ? { content_id: Number(item.id) }
        : { content_id: Number(item.id), type: kind === 'open' ? 'selected' : kind })
    }).then(function (r) { if (!r.ok) throw new Error('HTTP ' + r.status); return r; });
  }

  /* ---------- favourites strip ---------- */
  function renderRecent() {
    var ids = Object.keys(state.favs);
    recent.textContent = '';
    ids.slice(-12).reverse().forEach(function (id) {
      var item = state.favs[id];
      var img = document.createElement('img');
      img.src = item.thumb; img.alt = item.alt; img.loading = 'lazy'; img.tabIndex = 0;
      img.addEventListener('click', function () { openViewer(item); });
      img.addEventListener('keydown', function (e) { if (e.key === 'Enter') openViewer(item); });
      recent.appendChild(img);
    });
    recentWrap.classList.toggle('hidden', ids.length === 0);
  }

  /* ---------- favourite toggle (shared by grid + viewer) ---------- */
  var heartButtons = {};   // id -> [buttons]
  function paintHearts(item) {
    (heartButtons[item.id] || []).forEach(function (b) {
      b.setAttribute('aria-pressed', item.favorite ? 'true' : 'false');
      b.setAttribute('aria-label', item.favorite ? 'Remove from favourites' : 'Save as favourite');
    });
  }
  function toggleFavorite(item) {
    var on = !item.favorite;
    item.favorite = on;
    if (on) state.favs[item.id] = item; else delete state.favs[item.id];
    paintHearts(item); renderRecent();
    send(item, on ? 'favorite' : 'unfavorite').catch(function () {
      item.favorite = !on;
      if (item.favorite) state.favs[item.id] = item; else delete state.favs[item.id];
      paintHearts(item); renderRecent();
      toast('Could not save that. Please try again.');
    });
  }
  function makeHeart(item) {
    var b = document.createElement('button');
    b.type = 'button'; b.className = 'tile-heart';
    b.appendChild(icon('heart'));
    (heartButtons[item.id] = heartButtons[item.id] || []).push(b);
    paintHearts(item);
    b.addEventListener('click', function (e) { e.stopPropagation(); toggleFavorite(item); });
    return b;
  }

  /* ---------- tile ---------- */
  function buildTile(item) {
    var fig = document.createElement('figure');
    fig.className = 'tile';

    var open = document.createElement('button');
    open.type = 'button'; open.className = 'tile-open';
    open.setAttribute('aria-label', 'View picture bigger');
    var img = document.createElement('img');
    img.src = item.thumb; img.alt = item.alt; img.loading = 'lazy'; img.decoding = 'async';
    if (item.width && item.height) { img.width = item.width; img.height = item.height; }
    open.appendChild(img);
    open.addEventListener('click', function () { openViewer(item); });
    fig.appendChild(open);

    if (item.demo) {
      var b = document.createElement('span');
      b.className = 'tile-badge'; b.textContent = 'Demo';
      fig.appendChild(b);
    }
    fig.appendChild(makeHeart(item));

    if (item.credit) {
      var cap = document.createElement('figcaption');
      cap.className = 'tile-credit'; cap.textContent = 'Photo by ' + item.credit;
      fig.appendChild(cap);
    }
    return fig;
  }

  /* ---------- viewer (native <dialog>) ---------- */
  var dlg = null;
  function openViewer(item) {
    if (!dlg) {
      dlg = document.createElement('dialog');
      dlg.className = 'pg-viewer';
      dlg.addEventListener('click', function (e) { if (e.target === dlg) dlg.close(); });
      document.body.appendChild(dlg);
    }
    dlg.textContent = '';
    var wrap = document.createElement('div'); wrap.className = 'pg-viewer-body';

    var close = document.createElement('button');
    close.type = 'button'; close.className = 'pg-viewer-close';
    close.setAttribute('aria-label', 'Close'); close.appendChild(icon('x'));
    close.addEventListener('click', function () { dlg.close(); });

    var img = document.createElement('img');
    img.src = item.url || item.thumb; img.alt = item.alt;

    var bar = document.createElement('div'); bar.className = 'pg-viewer-bar';
    var credit = document.createElement('span');
    credit.className = 'small muted';
    credit.textContent = item.credit ? 'Photo by ' + item.credit : (item.demo ? 'Demo picture' : '');
    var heart = makeHeart(item); heart.className = 'tile-heart static';
    bar.appendChild(credit); bar.appendChild(heart);

    wrap.appendChild(close); wrap.appendChild(img); wrap.appendChild(bar);
    dlg.appendChild(wrap);
    if (typeof dlg.showModal === 'function') dlg.showModal(); else dlg.setAttribute('open', '');
    close.focus();
    send(item, 'open').catch(function () { });   // "open" is a light signal; failures are ignored
  }

  /* ---------- loading ---------- */
  function setLoading(on) {
    state.loading = on;
    skeleton.classList.toggle('hidden', !on);
    moreBtn.disabled = on;
    moreBtn.textContent = on ? 'Loading…' : 'Show more';
  }

  function load(reset) {
    if (state.loading) return;
    if (reset) {
      state.page = 1; state.hasMore = true; state.seen = {}; heartButtons = {};
      state.token++; grid.textContent = ''; emptyMsg.classList.add('hidden');
    }
    var token = state.token;
    setLoading(true);
    var params = new URLSearchParams();
    if (state.q) params.set('q', state.q);
    if (state.cat) params.set('cat', state.cat);
    params.set('page', state.page);
    params.set('limit', CONFIG.pageSize);

    fetch(CONFIG.listEndpoint + '?' + params.toString(), {
      credentials: 'same-origin', headers: { 'Accept': 'application/json' }
    }).then(function (r) {
      if (!r.ok) throw new Error('HTTP ' + r.status);
      return r.json();
    }).then(function (data) {
      if (token !== state.token) return;      // a newer search replaced this one
      var list = Array.isArray(data) ? data : (data.items || data.results || data.pictures || []);
      var frag = document.createDocumentFragment(), added = 0;
      list.forEach(function (raw) {
        var item = normalize(raw);
        if (!item.url && !item.thumb) return;
        if (state.seen[item.id]) return;      // no duplicate tiles
        state.seen[item.id] = true;
        if (item.favorite) state.favs[item.id] = item;
        frag.appendChild(buildTile(item)); added++;
      });
      grid.appendChild(frag);
      if (data && data.notice) toast(data.notice);   // e.g. "Using demo pictures"
      var more = data && typeof data.more === 'boolean' ? data.more
        : data && typeof data.has_more === 'boolean' ? data.has_more
          : list.length >= CONFIG.pageSize;
      state.hasMore = more && list.length > 0;
      state.page++;
      renderRecent();
      emptyMsg.classList.toggle('hidden', grid.children.length > 0);
      moreBtn.parentNode.classList.toggle('hidden', !state.hasMore);
    }).catch(function () {
      if (token !== state.token) return;
      toast('Could not load pictures. Check your connection and try again.');
    }).then(function () { if (token === state.token) setLoading(false); });
  }

  /* ---------- wiring ---------- */
  document.querySelectorAll('.topic[data-cat]').forEach(function (btn) {
    btn.addEventListener('click', function () {
      document.querySelectorAll('.topic').forEach(function (b) { b.setAttribute('aria-pressed', 'false'); });
      btn.setAttribute('aria-pressed', 'true');
      state.cat = btn.getAttribute('data-cat') || '';
      state.loading = false; load(true);
    });
  });

  var debounce = null;
  function runSearch() {
    var v = searchInput.value.trim();
    if (v === state.q) return;
    state.q = v; state.loading = false; load(true);
  }
  searchForm.addEventListener('submit', function (e) { e.preventDefault(); clearTimeout(debounce); runSearch(); });
  searchInput.addEventListener('input', function () { clearTimeout(debounce); debounce = setTimeout(runSearch, 400); });
  moreBtn.addEventListener('click', function () { load(false); });
  if ('IntersectionObserver' in window) {
    var loadObserver = new IntersectionObserver(function (entries) {
      if (entries.some(function (entry) { return entry.isIntersecting; }) && state.hasMore && !state.loading) {
        load(false);
      }
    }, { rootMargin: '700px 0px' });
    loadObserver.observe(moreBtn.parentNode);
  }

  var initial = new URLSearchParams(location.search).get('q');
  if (initial) { searchInput.value = initial; state.q = initial.trim(); }
  load(true);
})();