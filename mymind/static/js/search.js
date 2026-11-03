/* MyMind — global search. Adds a search button to the top bar of every page and opens a
   transparent glass search sheet. Self-contained: no inline scripts, nothing stored on the device. */
(function () {
    'use strict';

    /* ---------- CONFIG: adjust if your routes differ ---------- */
    var SCOPES = {
        pictures: { label: 'Pictures', api: '/api/pictures', page: '/pictures', q: true },
        videos: { label: 'Videos', api: '/api/videos', page: '/videos', q: true },
        shots: { label: 'Shorts', api: '/api/shots', page: '/shots', q: false },  // shots API has no text search: filtered here
        music: { label: 'Music', api: '/api/music', page: '/music', q: true }
    };
    var ORDER = ['pictures', 'videos', 'shots', 'music'];
    var LIMIT = 12, MIN_CHARS = 2, MAX_LEN = 60;

    var self = document.currentScript;
    if (document.querySelector('.public')) return;            // login / register pages: no search

    /* make sure the stylesheets are present even if base.html does not link them */
    (function ensureCss() {
        if (!self || !self.src) return;
        ['search.css', 'glass.css'].forEach(function (f) {
            if (document.querySelector('link[href*="' + f + '"]')) return;
            var l = document.createElement('link'); l.rel = 'stylesheet';
            l.href = self.src.replace(/js\/search\.js.*$/, 'css/' + f); document.head.appendChild(l);
        });
    })();

    /* ---------- helpers ---------- */
    var NS = 'http://www.w3.org/2000/svg';
    function el(tag, cls, text) { var n = document.createElement(tag); if (cls) n.className = cls; if (text != null) n.textContent = text; return n; }
    function svg(parts) {                                       // inline Lucide line icons (ISC licence)
        var s = document.createElementNS(NS, 'svg');
        s.setAttribute('class', 'ic'); s.setAttribute('viewBox', '0 0 24 24'); s.setAttribute('aria-hidden', 'true');
        parts.forEach(function (p) { var n = document.createElementNS(NS, p[0]); Object.keys(p[1]).forEach(function (k) { n.setAttribute(k, p[1][k]); }); s.appendChild(n); });
        return s;
    }
    var ICON_SEARCH = [['circle', { cx: 11, cy: 11, r: 8 }], ['path', { d: 'm21 21-4.3-4.3' }]];
    var ICON_X = [['path', { d: 'M18 6 6 18' }], ['path', { d: 'm6 6 12 12' }]];
    var ICON_RIGHT = [['path', { d: 'm9 18 6-6-6-6' }]];
    var ICON_ALERT = [['circle', { cx: 12, cy: 12, r: 10 }], ['path', { d: 'M12 8v4' }], ['path', { d: 'M12 16h.01' }]];

    function currentScope() {
        var p = location.pathname;
        for (var i = 0; i < ORDER.length; i++) if (p.indexOf(SCOPES[ORDER[i]].page) === 0) return ORDER[i];
        return 'pictures';
    }

    /* ---------- top-bar button ---------- */
    var bar = document.querySelector('.topbar');
    if (bar) {
        var right = bar.querySelector('.right');
        if (!right) {
            right = el('div', 'right');
            var sp = bar.querySelector('.spacer');
            if (sp) bar.replaceChild(right, sp); else bar.appendChild(right);
        }
        var ob = el('button', 'iconbtn'); ob.type = 'button'; ob.id = 'gs-open';
        ob.setAttribute('aria-label', 'Search'); ob.title = 'Search'; ob.appendChild(svg(ICON_SEARCH));
        ob.addEventListener('click', open);
        right.insertBefore(ob, right.firstChild);
    }

    /* ---------- overlay ---------- */
    var dlg = null, input, clearBtn, results, scopeBtns = {}, scope = currentScope(), token = 0, ctrl = null, timer = null;

    function build() {
        dlg = el('dialog', 'gs'); dlg.setAttribute('aria-label', 'Search');
        var panel = el('div', 'gs-panel');

        var top = el('form', 'gs-top'); top.setAttribute('role', 'search');
        var field = el('div', 'gs-field'); field.appendChild(svg(ICON_SEARCH));
        input = el('input', 'gs-input'); input.type = 'search'; input.maxLength = MAX_LEN; input.autocomplete = 'off';
        input.setAttribute('aria-label', 'Search'); input.placeholder = 'Search';
        clearBtn = el('button', 'gs-clear'); clearBtn.type = 'button'; clearBtn.hidden = true;
        clearBtn.setAttribute('aria-label', 'Clear'); clearBtn.appendChild(svg(ICON_X));
        field.append(input, clearBtn);
        var cancel = el('button', 'gs-cancel', 'Cancel'); cancel.type = 'button';
        top.append(field, cancel);

        var scopes = el('div', 'gs-scopes'); scopes.setAttribute('role', 'group'); scopes.setAttribute('aria-label', 'Search in');
        ORDER.forEach(function (k) {
            var b = el('button', 'gs-scope', SCOPES[k].label); b.type = 'button';
            b.addEventListener('click', function () { setScope(k); run(); });
            scopeBtns[k] = b; scopes.appendChild(b);
        });

        results = el('div', 'gs-results'); results.setAttribute('aria-live', 'polite');
        panel.append(top, scopes, results);
        dlg.appendChild(panel);
        document.body.appendChild(dlg);

        cancel.addEventListener('click', function () { dlg.close(); });
        dlg.addEventListener('click', function (e) { if (e.target === dlg) dlg.close(); });   // tap outside the panel
        dlg.addEventListener('close', function () { if (ctrl) ctrl.abort(); clearTimeout(timer); });
        clearBtn.addEventListener('click', function () { input.value = ''; input.focus(); run(); });
        input.addEventListener('input', function () { clearTimeout(timer); timer = setTimeout(run, 350); clearBtn.hidden = !input.value; });
        top.addEventListener('submit', function (e) {
            e.preventDefault();
            var q = input.value.trim();
            if (q.length >= MIN_CHARS && SCOPES[scope].q) location.href = SCOPES[scope].page + '?q=' + encodeURIComponent(q);
            else run();
        });
    }

    function setScope(k) {
        scope = k;
        ORDER.forEach(function (x) { scopeBtns[x].setAttribute('aria-pressed', x === k ? 'true' : 'false'); });
        input.placeholder = 'Search ' + SCOPES[k].label.toLowerCase();
    }

    function open() {
        if (!dlg) build();
        setScope(scope);
        if (typeof dlg.showModal === 'function') dlg.showModal(); else dlg.setAttribute('open', '');
        input.focus(); input.select();
        run();
    }

    /* ---------- states ---------- */
    function msg(icon, text, small) {
        var m = el('div', 'gs-msg'); m.appendChild(svg(icon)); m.appendChild(el('div', null, text));
        if (small) m.appendChild(el('small', null, small));
        results.replaceChildren(m);
    }
    function hint() { msg(ICON_SEARCH, 'Search pictures, videos, shorts and music', 'Type at least ' + MIN_CHARS + ' letters'); }
    function loading() { var f = document.createDocumentFragment(); for (var i = 0; i < 4; i++) f.appendChild(el('div', 'gs-sk')); results.replaceChildren(f); }

    /* ---------- fetching ---------- */
    function getJson(url, signal) {
        return fetch(url, { credentials: 'same-origin', headers: { 'Accept': 'application/json' }, signal: signal })
            .then(function (r) { if (!r.ok) throw new Error('HTTP ' + r.status); return r.json(); });
    }
    function listOf(d) { return Array.isArray(d) ? d : (d && (d.items || d.results || d.pictures || d.videos || d.tracks || d.shots)) || []; }
    function normalize(r) {
        var at = r.attribution || {};
        return {
            title: r.title || r.name || r.alt || 'Untitled',
            sub: r.artist || r.channel || r.channel_title || at.channel || r.photographer || r.credit || r.category_label || '',
            thumb: r.thumb || r.thumbnail || r.image_url || r.artwork || r.cover || r.src || ''
        };
    }
    function fetchList(sc, q, signal) {
        if (sc.q) {
            return getJson(sc.api + '?q=' + encodeURIComponent(q) + '&page=1&limit=' + LIMIT, signal).then(listOf);
        }
        var low = q.toLowerCase();                                  // shorts: no server text search, so filter the first pages here
        return Promise.all([1, 2].map(function (p) { return getJson(sc.api + '?page=' + p, signal).then(listOf).catch(function () { return []; }); }))
            .then(function (pages) {
                return [].concat.apply([], pages).filter(function (r) {
                    var n = normalize(r);
                    return (n.title + ' ' + n.sub + ' ' + (r.category_label || '')).toLowerCase().indexOf(low) > -1;
                }).slice(0, LIMIT);
            });
    }

    function run() {
        if (!dlg) return;
        var q = input.value.trim();
        clearBtn.hidden = !input.value;
        if (ctrl) ctrl.abort();
        if (q.length < MIN_CHARS) { hint(); return; }
        var sc = SCOPES[scope], my = ++token;
        loading();
        ctrl = window.AbortController ? new AbortController() : null;
        fetchList(sc, q, ctrl ? ctrl.signal : undefined).then(function (list) {
            if (my !== token) return;
            render(list, q, sc);
        }).catch(function (e) {
            if ((e && e.name === 'AbortError') || my !== token) return;
            msg(ICON_ALERT, 'Search is not available right now', 'Please try again in a moment');
        });
    }

    function render(list, q, sc) {
        if (!list.length) { msg(ICON_SEARCH, 'No ' + sc.label.toLowerCase() + ' found for \u201c' + q + '\u201d', 'Try another word, or switch the type above'); return; }
        var href = sc.q ? sc.page + '?q=' + encodeURIComponent(q) : sc.page;
        var frag = document.createDocumentFragment();
        list.forEach(function (raw) {
            var n = normalize(raw);
            var a = el('a', 'gs-row'); a.href = href;
            var th = el('span', 'gs-thumb');
            if (n.thumb) { var im = el('img'); im.src = n.thumb; im.alt = ''; im.loading = 'lazy'; th.appendChild(im); }
            var tx = el('span', 'gs-text'); tx.appendChild(el('span', 'gs-title', n.title));
            if (n.sub) tx.appendChild(el('span', 'gs-sub', n.sub));
            var go = el('span', 'gs-go'); go.appendChild(svg(ICON_RIGHT));
            a.append(th, tx, go); frag.appendChild(a);
        });
        var all = el('a', 'gs-all', sc.q ? 'See all results in ' + sc.label : 'Open ' + sc.label); all.href = href;
        frag.appendChild(all);
        results.replaceChildren(frag);
    }

    window.MyMindSearch = { open: open };
})();