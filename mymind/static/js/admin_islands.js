/* Admin → 3D World & Island Management. Confirmation dialogs for every destructive or world-wide action.
   The server checks the confirmation too (confirm=yes, and the typed phrase for "delete all"), so this page only collects it.
   Island names are written with textContent. */
(function () {
  "use strict";
  var root = document.getElementById("isl-root");
  if (!root) return;
  var $ = function (id) { return document.getElementById(id); };
  var urls = JSON.parse($("isl-urls").textContent), csrf = root.dataset.csrf;
  var dlg = $("isl-dialog"), form = $("isl-dialog-form"), confirmBtn = $("isl-confirm");
  var all = $("isl-all"), bulk = $("isl-bulk"), count = $("isl-count");

  function checks() { return Array.prototype.slice.call(document.querySelectorAll(".isl-check:not(:disabled)")); }
  function chosen() { return checks().filter(function (c) { return c.checked; }); }
  function sync() {
    var n = chosen().length;
    if (count) count.textContent = String(n);
    if (bulk) bulk.disabled = n === 0;
    if (all) { all.checked = n > 0 && n === checks().length; all.indeterminate = n > 0 && n < checks().length; }
    document.querySelectorAll(".isl-card").forEach(function (c) { var k = c.querySelector(".isl-check"); c.classList.toggle("is-picked", !!(k && k.checked)); });
  }
  if (all) all.addEventListener("change", function () { checks().forEach(function (c) { c.checked = all.checked; }); sync(); });
  document.addEventListener("change", function (e) { if (e.target.classList && e.target.classList.contains("isl-check")) sync(); });

  function hidden(name, value) { var i = document.createElement("input"); i.type = "hidden"; i.name = name; i.value = value; return i; }
  function open(o) {
    $("isl-dialog-title").textContent = o.title;
    $("isl-dialog-text").textContent = o.text;
    var list = $("isl-dialog-list"); list.replaceChildren();
    (o.names || []).slice(0, 12).forEach(function (n) { var li = document.createElement("li"); li.textContent = n; list.appendChild(li); });
    if ((o.names || []).length > 12) { var more = document.createElement("li"); more.textContent = "…and " + (o.names.length - 12) + " more"; list.appendChild(more); }
    var typed = $("isl-dialog-typed"); typed.hidden = !o.typed; $("isl-phrase").value = ""; $("isl-phrase").required = !!o.typed;
    form.action = o.action;
    var h = $("isl-dialog-hidden"); h.replaceChildren(hidden("csrf_token", csrf), hidden("confirm", "yes"));
    (o.ids || []).forEach(function (id) { h.appendChild(hidden("ids", id)); });
    if (o.extra) Object.keys(o.extra).forEach(function (k) { h.appendChild(hidden(k, o.extra[k])); });
    confirmBtn.textContent = o.button; confirmBtn.className = "btn " + (o.danger ? "red" : "primary");
    if (dlg.showModal) dlg.showModal(); else dlg.setAttribute("open", "");
    (o.typed ? $("isl-phrase") : confirmBtn).focus();
  }
  $("isl-cancel").addEventListener("click", function () { if (dlg.close) dlg.close(); else dlg.removeAttribute("open"); });
  dlg.addEventListener("click", function (e) { if (e.target === dlg) dlg.close(); });
  form.addEventListener("submit", function () { confirmBtn.disabled = true; });

  document.addEventListener("click", function (e) {
    var b = e.target.closest("[data-act]"); if (!b) return;
    var li = b.closest("[data-id]"); if (!li) return;
    var id = li.dataset.id, name = li.dataset.name, act = b.dataset.act;
    if (act === "default") open({ title: "Set as default world?", action: urls["default"], ids: [], extra: { id: id }, names: [name], button: "Set as Default World",
      text: "This island becomes the shared 3D world for every child account, on every device. Each child's own activity and interests still personalise it. Children's history is not changed." });
    else if (act === "delete") open({ title: "Delete this island?", action: urls["delete"], ids: [id], names: [name], button: "Delete island", danger: true,
      text: "Are you sure you want to delete this island? This action will remove it from the available world maps. You can restore it from “Recently deleted”. Children's activity is not affected." });
    else if (act === "purge") open({ title: "Remove permanently?", action: urls.purge, ids: [id], names: [name], button: "Remove permanently", danger: true,
      text: "This island and its files will be erased for good and cannot be restored. Files used by another model are kept." });
  });
  if (bulk) bulk.addEventListener("click", function () {
    var picked = chosen(); if (!picked.length) return;
    open({ title: "Delete " + picked.length + " island" + (picked.length === 1 ? "" : "s") + "?", action: urls["delete"], danger: true, button: "Delete " + picked.length + " selected",
      ids: picked.map(function (c) { return c.value; }), names: picked.map(function (c) { return c.closest("[data-name]").dataset.name; }),
      text: "These islands will be removed from the available world maps. You can restore them from “Recently deleted”. The default world is not included." });
  });
  var delAll = $("isl-deleteall");
  if (delAll) delAll.addEventListener("click", function () {
    open({ title: "Delete ALL islands and start fresh?", action: urls.deleteAll, danger: true, typed: true, button: "Delete all islands", ids: [],
      text: "Every island, including the current default world, is removed and the default is reset. Children will see MyMind's built-in map until you choose a new default. Their activity and accounts are not touched. You can still restore islands from “Recently deleted”." });
  });
  var purgeAll = $("isl-purgeall");
  if (purgeAll) purgeAll.addEventListener("click", function () {
    open({ title: "Remove all deleted islands permanently?", action: urls.purge, danger: true, button: "Remove all permanently", ids: [], extra: { all: "yes" },
      text: "Every island in “Recently deleted” will be erased for good. This cannot be undone." });
  });
  sync();
})();
