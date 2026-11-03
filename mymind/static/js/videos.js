/* MyMind — Videos page. Self-contained (no inline scripts, CSP-safe).
   Featured player + "Up next" sidebar + "Recommended videos" grid.
   Videos only play in the official YouTube embed, and only after a tap. */
(function () {
    'use strict';

    /* ---------- CONFIG: adjust if your backend differs ---------- */
    var CONFIG = {
        listEndpoint: '/api/videos',            // GET ?q=&cat=&page=&limit=
        interactEndpoint: '/api/interactions',  // POST JSON {item_id, type, kind}
        embedBase: 'https://www.youtube.com/embed/',  // must be allowed by your CSP frame-src
        pageSize: 24,
        sideCount: 7,                           // how many items go in "Up next"
        iconPrefix: '#i-'                       // must match ids in templates/_icons.html
    };

    var $ = function (id) { return document.getElementById(id); };
    var stage = $('stage'), side = $('side'), grid = $('grid'), emptyMsg = $('empty'),
        moreBtn = $('more'), searchForm = $('search'), searchInput = $('q'),
        vTitle = $('v-title'), vMeta = $('v-meta'), vFav = $('v-fav'), vFavText = $('v-fav-text'),
        vReason = $('v-reason'), vReasonText = $('v-reason-text');
    if (!stage) { classicMode(); return; }   // old videos.html: no player area, just #grid

    var state = {
        cat: '', q: '', page: 1, loading: false, hasMore: true,
        seen: {}, count: 0, featured: null, token: 0
    };

    /* ---------- helpers ---------- */
    function csrfToken() {
        var m = document.querySelector('meta[name="csrf-token"]');
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
        box.appendChild(t); setTimeout(function () { t.remove(); }, 3500);
    }
    function icon(name, cls) {
        var ns = 'http://www.w3.org/2000/svg';
        var svg = document.createElementNS(ns, 'svg');
        svg.setAttribute('class', 'ic' + (cls ? ' ' + cls : ''));
        svg.setAttribute('aria-hidden', 'true');
        var use = document.createElementNS(ns, 'use');
        use.setAttribute('href', CONFIG.iconPrefix + name);
        svg.appendChild(use); return svg;
    }
    function el(tag, cls, text) {
        var n = document.createElement(tag);
        if (cls) n.className = cls;
        if (text != null) n.textContent = text;
        return n;
    }
    function fmtDuration(d) {
        if (d == null || d === '') return '';
        if (typeof d === 'string' && d.indexOf(':') > -1) return d;
        var s = Math.round(Number(d)); if (!isFinite(s) || s <= 0) return '';
        var h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), r = s % 60;
        var pad = function (n) { return n < 10 ? '0' + n : '' + n; };
        return h ? h + ':' + pad(m) + ':' + pad(r) : m + ':' + pad(r);
    }
    function fmtViews(v) {
        var n = Number(v); if (!isFinite(n) || n <= 0) return '';
        if (n >= 1e6) return (n / 1e6).toFixed(1).replace(/\.0$/, '') + 'M views';
        if (n >= 1e3) return (n / 1e3).toFixed(1).replace(/\.0$/, '') + 'K views';
        return n + ' views';
    }
    function normalize(raw) {
        var yt = raw.video_id || raw.youtube_id || raw.yt_id || '';
        if (!yt && typeof raw.id === 'string' && /^[A-Za-z0-9_-]{11}$/.test(raw.id)) yt = raw.id;
        var secs = raw.duration_seconds != null ? raw.duration_seconds : raw.duration;
        return {
            id: String(raw.id != null ? raw.id : (raw.item_id != null ? raw.item_id : yt)),
            yt: yt,
            title: raw.title || 'Untitled video',
            channel: raw.channel || raw.channel_title || raw.author || '',
            thumb: raw.thumb || raw.thumbnail || raw.image_url || (yt ? 'https://i.ytimg.com/vi/' + yt + '/hqdefault.jpg' : ''),
            duration: fmtDuration(secs),
            short: Number(secs) > 0 && Number(secs) <= 60,
            views: fmtViews(raw.views || raw.view_count),
            reason: raw.reason || '',
            demo: !!(raw.demo || raw.is_demo),
            favorite: !!(raw.favorite || raw.is_favorite || raw.favourite)
        };
    }
    function send(item, kind) {
        return fetch(CONFIG.interactEndpoint, {
            method: 'POST', credentials: 'same-origin',
            headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrfToken(), 'X-CSRF-Token': csrfToken() },
            body: JSON.stringify({ item_id: item.id, type: 'video', kind: kind })
        }).then(function (r) { if (!r.ok) throw new Error('HTTP ' + r.status); return r; });
    }


    /* ---------- CLASSIC MODE ----------
       Used when the page is the OLD videos.html (only #grid, #q, #more, .chip).
       Draws its own clean cards: thumbnail on top, title and channel BELOW in normal
       flow, so one card can never cover the words of another. Needs no CSS file. */
    function classicMode() {
        var grid = $('grid'), more = $('more'), form = $('search'), input = $('q');
        if (!grid) return;
        var st = { cat: '', q: '', page: 1, loading: false, hasMore: true, seen: {}, token: 0 };
        function S(node, styles) {
            Object.keys(styles).forEach(function (k) { node.style.setProperty(k, styles[k]); });
            return node;
        }
        S(grid, {
            'display': 'grid', 'grid-template-columns': 'repeat(2, minmax(0, 1fr))',
            'grid-auto-rows': 'auto', 'gap': '1.3rem .8rem', 'align-items': 'start', 'column-count': 'auto'
        });

        function card(item) {
            var c = S(el('div', 'vclassic'), { 'display': 'block', 'min-width': '0', 'position': 'static', 'height': 'auto', 'aspect-ratio': 'auto', 'overflow': 'visible' });
            var th = S(el('button'), {
                'position': 'relative', 'display': 'block', 'width': '100%', 'padding': '0',
                'border': '0', 'background': 'var(--sky2)', 'border-radius': '14px', 'overflow': 'hidden',
                'cursor': 'pointer', 'aspect-ratio': '16 / 9'
            });
            th.type = 'button'; th.setAttribute('aria-label', 'Play ' + item.title);
            if (item.thumb) {
                var im = S(el('img'), { 'width': '100%', 'height': '100%', 'object-fit': 'cover', 'display': 'block' });
                im.src = item.thumb; im.alt = ''; im.loading = 'lazy'; th.appendChild(im);
            }
            var pb = S(el('span'), {
                'position': 'absolute', 'left': '50%', 'top': '50%', 'transform': 'translate(-50%,-50%)',
                'width': '46px', 'height': '46px', 'border-radius': '50%', 'background': 'rgba(255,255,255,.95)',
                'color': 'var(--blue)', 'display': 'grid', 'place-items': 'center', 'box-shadow': '0 4px 14px rgba(0,0,0,.3)'
            });
            var pi = icon('play'); pi.style.setProperty('fill', 'currentColor'); pi.style.setProperty('margin-left', '3px');
            pb.appendChild(pi); th.appendChild(pb);
            if (item.duration) th.appendChild(S(el('span', null, item.duration), {
                'position': 'absolute', 'right': '.4rem',
                'bottom': '.4rem', 'background': 'rgba(17,24,39,.82)', 'color': '#fff', 'font-size': '.7rem',
                'font-weight': '800', 'padding': '.1rem .45rem', 'border-radius': '6px'
            }));
            if (item.demo) th.appendChild(S(el('span', null, 'Demo'), {
                'position': 'absolute', 'left': '.4rem', 'top': '.4rem',
                'background': 'var(--ink)', 'color': '#fff', 'font-size': '.64rem', 'font-weight': '800',
                'padding': '.1rem .5rem', 'border-radius': '999px'
            }));
            th.addEventListener('click', function () {
                if (item.demo || !item.yt) { toast('This is a demo video. Add a YouTube API key to play real videos.'); return; }
                var f = S(document.createElement('iframe'), { 'position': 'absolute', 'inset': '0', 'width': '100%', 'height': '100%', 'border': '0' });
                f.src = CONFIG.embedBase + encodeURIComponent(item.yt) + '?autoplay=1&rel=0&playsinline=1&modestbranding=1';
                f.title = item.title; f.allow = 'autoplay; encrypted-media; picture-in-picture; fullscreen';
                f.setAttribute('allowfullscreen', ''); f.referrerPolicy = 'strict-origin-when-cross-origin';
                th.textContent = ''; th.style.setProperty('cursor', 'default'); th.appendChild(f);
                send(item, 'watched').catch(function () { });
            });
            c.appendChild(th);

            c.appendChild(S(el('div', null, item.title), {
                'display': '-webkit-box', '-webkit-line-clamp': '2',
                '-webkit-box-orient': 'vertical', 'overflow': 'hidden', 'margin-top': '.55rem', 'font-weight': '800',
                'font-size': '.92rem', 'line-height': '1.3', 'color': 'var(--navy)', 'position': 'static'
            }));
            var sub = [item.channel, item.views].filter(Boolean).join(' \u00b7 ');
            if (sub) c.appendChild(S(el('div', null, sub), {
                'margin-top': '.15rem', 'font-size': '.8rem',
                'font-weight': '700', 'color': 'var(--muted)'
            }));
            return c;
        }

        function run(reset) {
            if (st.loading) return;
            if (reset) { st.page = 1; st.hasMore = true; st.seen = {}; st.token++; grid.textContent = ''; }
            var token = st.token; st.loading = true;
            if (more) { more.disabled = true; more.textContent = 'Loading\u2026'; }
            var p = new URLSearchParams();
            if (st.q) p.set('q', st.q);
            if (st.cat) p.set('cat', st.cat);
            p.set('page', st.page); p.set('limit', CONFIG.pageSize);
            fetch(CONFIG.listEndpoint + '?' + p.toString(), { credentials: 'same-origin', headers: { 'Accept': 'application/json' } })
                .then(function (r) { if (!r.ok) throw new Error('HTTP ' + r.status); return r.json(); })
                .then(function (data) {
                    if (token !== st.token) return;
                    var list = Array.isArray(data) ? data : (data.items || data.results || data.videos || []);
                    var frag = document.createDocumentFragment();
                    list.forEach(function (raw) {
                        var item = normalize(raw);
                        if (!item.title || st.seen[item.id]) return;
                        st.seen[item.id] = true; frag.appendChild(card(item));
                    });
                    grid.appendChild(frag);
                    if (data && data.notice) toast(data.notice);
                    var m = (data && typeof data.has_more === 'boolean') ? data.has_more : list.length >= CONFIG.pageSize;
                    st.hasMore = m && list.length > 0; st.page++;
                    if (more && more.parentNode) more.parentNode.style.setProperty('display', st.hasMore ? '' : 'none');
                })
                .catch(function () { if (token === st.token) toast('Could not load videos. Check your connection and try again.'); })
                .then(function () { if (token === st.token) { st.loading = false; if (more) { more.disabled = false; more.textContent = 'Show more'; } } });
        }

        document.querySelectorAll('.chip[data-cat]').forEach(function (b) {
            b.addEventListener('click', function () {
                document.querySelectorAll('.chip[data-cat]').forEach(function (x) { x.setAttribute('aria-pressed', 'false'); });
                b.setAttribute('aria-pressed', 'true'); st.cat = b.getAttribute('data-cat') || ''; st.loading = false; run(true);
            });
        });
        var t = null;
        function go() { var v = input ? input.value.trim() : ''; if (v === st.q) return; st.q = v; st.loading = false; run(true); }
        if (form) form.addEventListener('submit', function (e) { e.preventDefault(); clearTimeout(t); go(); });
        if (input) input.addEventListener('input', function () { clearTimeout(t); t = setTimeout(go, 400); });
        if (more) more.addEventListener('click', function () { run(false); });
        var q0 = new URLSearchParams(location.search).get('q');
        if (q0 && input) { input.value = q0; st.q = q0.trim(); }
        run(true);
    }

    /* ---------- featured stage ---------- */
    function renderStage(item) {
        stage.textContent = '';
        stage.classList.remove('sk');

        var poster = el('button', 'vp-poster');
        poster.type = 'button';
        poster.setAttribute('aria-label', 'Play ' + item.title);
        if (item.thumb) {
            var img = el('img'); img.src = item.thumb; img.alt = ''; img.decoding = 'async';
            poster.appendChild(img);
        }
        if (item.channel) {
            var chip = el('span', 'vp-chip');
            chip.appendChild(el('span', 'vp-avatar', item.channel.charAt(0).toUpperCase()));
            chip.appendChild(el('span', 'vp-chip-name', item.channel));
            poster.appendChild(chip);
        }
        if (item.demo) poster.appendChild(el('span', 'vp-tag demo', 'Demo'));
        else if (item.short) poster.appendChild(el('span', 'vp-tag', 'Short'));
        var play = el('span', 'vp-play'); play.appendChild(icon('play')); poster.appendChild(play);
        if (item.duration) poster.appendChild(el('span', 'vp-dur-big', item.duration));
        poster.addEventListener('click', function () { playItem(item); });
        stage.appendChild(poster);
    }

    function playItem(item) {
        if (item.demo || !item.yt) {
            toast('This is a demo video. Add a YouTube API key to play real videos.');
            return;
        }
        var f = document.createElement('iframe');
        f.className = 'vp-frame';
        f.src = CONFIG.embedBase + encodeURIComponent(item.yt) + '?autoplay=1&rel=0&playsinline=1&modestbranding=1';
        f.title = item.title;
        f.allow = 'autoplay; encrypted-media; picture-in-picture; fullscreen';
        f.setAttribute('allowfullscreen', '');
        f.referrerPolicy = 'strict-origin-when-cross-origin';
        stage.textContent = ''; stage.appendChild(f);
        send(item, 'watched').catch(function () { });   // light signal; failures ignored
    }

    /* ---------- info panel ---------- */
    function paintFav(item) {
        vFav.setAttribute('aria-pressed', item.favorite ? 'true' : 'false');
        vFavText.textContent = item.favorite ? 'Saved' : 'Save';
    }
    function renderInfo(item) {
        vTitle.textContent = item.title;
        var bits = [item.channel, item.duration, item.views].filter(Boolean);
        vMeta.textContent = bits.join('  \u00b7  ');
        paintFav(item);
        if (item.reason) { vReasonText.textContent = item.reason; vReason.classList.remove('hidden'); }
        else vReason.classList.add('hidden');
    }
    vFav.addEventListener('click', function () {
        var item = state.featured; if (!item) return;
        var on = !item.favorite; item.favorite = on; paintFav(item);
        send(item, on ? 'favorite' : 'unfavorite').catch(function () {
            item.favorite = !on; paintFav(item);
            toast('Could not save that. Please try again.');
        });
    });

    /* ---------- selection ---------- */
    function select(item, scroll) {
        state.featured = item;
        renderStage(item); renderInfo(item);
        document.querySelectorAll('.vcard[data-id]').forEach(function (c) {
            var on = c.getAttribute('data-id') === item.id;
            c.classList.toggle('active', on);
            if (on) c.setAttribute('aria-current', 'true'); else c.removeAttribute('aria-current');
        });
        if (scroll) {
            var r = stage.getBoundingClientRect();
            if (r.top < 0 || r.bottom > window.innerHeight) stage.scrollIntoView({ block: 'start' });
        }
    }

    /* ---------- cards ---------- */
    function buildCard(item, row) {
        var b = el('button', 'vcard'); b.type = 'button';
        b.setAttribute('data-id', item.id);
        b.setAttribute('aria-label', 'Watch ' + item.title);
        var th = el('span', 'vthumb');
        if (item.thumb) { var i = el('img'); i.src = item.thumb; i.alt = ''; i.loading = 'lazy'; i.decoding = 'async'; th.appendChild(i); }
        if (item.demo) th.appendChild(el('span', 'vdemo', 'Demo'));
        if (item.duration) th.appendChild(el('span', 'vdur', item.duration));
        var tx = el('span', 'vtext');
        tx.appendChild(el('span', 'vtitle', item.title));
        var sub = [item.channel, item.views].filter(Boolean).join(' \u00b7 ');
        if (sub) tx.appendChild(el('span', 'vsub', sub));
        b.appendChild(th);
        // sidebar rows keep thumb + text side by side; grid cards stack them
        if (row) { var wrap = el('span'); wrap.style.minWidth = '0'; wrap.appendChild(tx); b.appendChild(wrap); }
        else { tx.style.display = 'block'; b.appendChild(tx); }
        b.addEventListener('click', function () { select(item, true); });
        return b;
    }

    function skeletons() {
        side.textContent = ''; grid.textContent = '';
        stage.textContent = ''; stage.classList.add('sk');
        for (var i = 0; i < 4; i++) { var li = el('li'); li.appendChild(el('div', 'vsk row')); side.appendChild(li); }
        for (var j = 0; j < 4; j++) grid.appendChild(el('div', 'vsk card'));
    }
    function clearSkeletons() {
        side.textContent = ''; grid.textContent = '';
    }

    /* ---------- loading ---------- */
    function setLoading(on) {
        state.loading = on;
        moreBtn.disabled = on;
        moreBtn.textContent = on ? 'Loading\u2026' : 'Show more';
    }

    function load(reset) {
        if (state.loading) return;
        if (reset) {
            state.page = 1; state.hasMore = true; state.seen = {}; state.count = 0;
            state.featured = null; state.token++;
            emptyMsg.classList.add('hidden'); skeletons();
            vTitle.textContent = 'Loading\u2026'; vMeta.textContent = ''; vReason.classList.add('hidden');
        }
        var token = state.token;
        setLoading(true);
        var p = new URLSearchParams();
        if (state.q) p.set('q', state.q);
        if (state.cat) p.set('cat', state.cat);
        p.set('page', state.page); p.set('limit', CONFIG.pageSize);

        fetch(CONFIG.listEndpoint + '?' + p.toString(), { credentials: 'same-origin', headers: { 'Accept': 'application/json' } })
            .then(function (r) { if (!r.ok) throw new Error('HTTP ' + r.status); return r.json(); })
            .then(function (data) {
                if (token !== state.token) return;
                var list = Array.isArray(data) ? data : (data.items || data.results || data.videos || []);
                if (reset) clearSkeletons();
                var sideFrag = document.createDocumentFragment(), gridFrag = document.createDocumentFragment();
                list.forEach(function (raw) {
                    var item = normalize(raw);
                    if (!item.title || state.seen[item.id]) return;
                    state.seen[item.id] = true;
                    if (state.count === 0) { state.featured = item; }
                    else if (state.count <= CONFIG.sideCount) {
                        var li = el('li'); li.appendChild(buildCard(item, true)); sideFrag.appendChild(li);
                    } else { gridFrag.appendChild(buildCard(item, false)); }
                    state.count++;
                });
                side.appendChild(sideFrag); grid.appendChild(gridFrag);
                if (reset && state.featured) select(state.featured, false);
                if (data && data.notice) toast(data.notice);
                var more = (data && typeof data.has_more === 'boolean') ? data.has_more : list.length >= CONFIG.pageSize;
                state.hasMore = more && list.length > 0; state.page++;
                moreBtn.parentNode.classList.toggle('hidden', !state.hasMore);
                if (state.count === 0) {
                    stage.textContent = ''; stage.classList.remove('sk');
                    vTitle.textContent = 'No videos found'; emptyMsg.classList.remove('hidden');
                }
            })
            .catch(function () {
                if (token !== state.token) return;
                if (reset) { clearSkeletons(); stage.textContent = ''; stage.classList.remove('sk'); vTitle.textContent = 'Could not load videos'; }
                toast('Could not load videos. Check your connection and try again.');
            })
            .then(function () { if (token === state.token) setLoading(false); });
    }

    /* ---------- wiring ---------- */
    document.querySelectorAll('.vp-tab[data-cat]').forEach(function (btn) {
        btn.addEventListener('click', function () {
            document.querySelectorAll('.vp-tab').forEach(function (b) { b.setAttribute('aria-pressed', 'false'); });
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

    var initial = new URLSearchParams(location.search).get('q');
    if (initial) { searchInput.value = initial; state.q = initial.trim(); }
    load(true);
})();