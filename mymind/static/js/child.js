/* MyMind — child theme helpers (loaded only for a signed-in child; CSP-safe, no inline script).
   The search button in the top bar opens the page's own search box, then puts the cursor in it.
   Tapping the button again closes it. Nothing is stored or sent. */
(function () {
  'use strict';
  var body = document.body;

  function box() {
    return document.querySelector('#q, #sh-q, .vp-search input, input[type="search"]');
  }

  document.addEventListener('click', function (e) {
    var btn = e.target.closest ? e.target.closest('[data-focus-search]') : null;
    if (!btn) return;
    e.preventDefault();
    var open = body.classList.toggle('ch-search-open');
    btn.setAttribute('aria-expanded', open ? 'true' : 'false');
    if (open) {
      var input = box();
      if (input) {
        try { input.scrollIntoView({ block: 'center', behavior: 'smooth' }); } catch (err) { input.scrollIntoView(); }
        setTimeout(function () { input.focus(); }, 250);
      }
    }
  });
})();
