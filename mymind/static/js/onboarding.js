(function () {
  const steps = [...document.querySelectorAll(".step")]; if (!steps.length) return;
  const bars = [...document.querySelectorAll(".steps i")]; const next = document.getElementById("wiz-next"), back = document.getElementById("wiz-back"), submit = document.getElementById("wiz-submit");
  let i = 0;
  function show(n) {
    i = Math.max(0, Math.min(n, steps.length - 1));
    steps.forEach((s, k) => (s.hidden = k !== i)); bars.forEach((b, k) => b.classList.toggle("on", k <= i));
    back.hidden = i === 0; const last = i === steps.length - 1; next.hidden = last; submit.hidden = !last;
    next.textContent = i === 0 ? "Start" : "Next"; window.scrollTo({ top: 0, behavior: "smooth" });
  }
  next.onclick = () => show(i + 1); back.onclick = () => show(i - 1);
  document.querySelectorAll("[data-go]").forEach((b) => b.addEventListener("click", () => show(parseInt(b.dataset.go, 10))));
  document.getElementById("wizard").addEventListener("submit", (e) => { const c = document.querySelector("input[name=consent]"); if (c && !c.checked) { e.preventDefault(); show(steps.length - 1); c.focus(); } });
  show(0);
})();
