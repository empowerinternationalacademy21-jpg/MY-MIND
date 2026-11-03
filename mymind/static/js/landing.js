/* Highlight the nav link of the section currently in view (progressive enhancement). */
(function () {
    const links = [...document.querySelectorAll("[data-nav]")]; if (!links.length || !("IntersectionObserver" in window)) return;
    const map = new Map(links.map((a) => [a.getAttribute("href").slice(1), a]));
    const io = new IntersectionObserver((entries) => {
        entries.forEach((e) => { if (e.isIntersecting) { links.forEach((l) => l.classList.remove("on")); const a = map.get(e.target.id); if (a) a.classList.add("on"); } });
    }, { rootMargin: "-40% 0px -50% 0px" });
    map.forEach((_, id) => { const s = document.getElementById(id); if (s) io.observe(s); });
})();