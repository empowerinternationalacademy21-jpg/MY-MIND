(async function () {
  const MM = window.MyMind; const id = document.querySelector('meta[name="item"]').content;
  ["pictures", "videos", "songs"].forEach((k) => document.getElementById(k).replaceChildren(MM.skeletons(4)));
  try {
    const d = await MM.api("/api/related/" + id); MM.notice(document.getElementById("wrap"), d.notice);
    ["pictures", "videos", "songs"].forEach((k) => MM.renderItems(document.getElementById(k), d[k]));
  } catch (e) { MM.toast(e.message); }
})();
