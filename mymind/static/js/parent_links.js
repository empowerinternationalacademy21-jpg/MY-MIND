(function () {
  document.addEventListener("click", function (e) {
    var b = e.target.closest("[data-copy]");
    if (!b) return;
    var input = document.querySelector(b.getAttribute("data-copy"));
    if (!input) return;
    input.select();
    var done = function () { b.textContent = "Copied"; setTimeout(function () { b.textContent = "Copy link"; }, 2000); };
    if (navigator.clipboard && navigator.clipboard.writeText) navigator.clipboard.writeText(input.value).then(done, function () { document.execCommand("copy"); done(); });
    else { document.execCommand("copy"); done(); }
  });
})();
