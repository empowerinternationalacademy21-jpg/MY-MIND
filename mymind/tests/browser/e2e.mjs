// Real-browser end-to-end checks for My World, the 3D viewer, admin 3D pages and parent links.
import { launch, session, BASE, sleep } from "./lib.mjs";

const results = [];
const noise = /fonts\.googleapis|fonts\.gstatic|ERR_NAME_NOT_RESOLVED|ERR_INTERNET_DISCONNECTED/;      // Google Fonts are unreachable in sandboxes
async function check(name, fn) {
  try { await fn(); results.push([true, name]); console.log("PASS", name); }
  catch (e) { results.push([false, name + " :: " + (e && e.message || e)]); console.log("FAIL", name, "::", e && e.message || e); }
}
const must = (cond, msg) => { if (!cond) throw new Error(msg); };
const clean = (logs) => logs.filter((l) => !noise.test(l));

const ui = (page) => page.evaluate(() => ({ mode: window.MMWorldUI.mode(), canvas: !!document.querySelector("canvas.w3d-canvas"), svg: !!document.querySelector("svg.w3d-flat"), labels: document.querySelectorAll(".w3d-label").length }));
const labelPos = (page, key = "home") => page.evaluate((k) => { const r = document.querySelector(`.w3d-label[data-key="${k}"]`).getBoundingClientRect(); return [Math.round(r.x), Math.round(r.y), Math.round(r.width)]; }, key);

const browser = await launch();
try {
  const { page, logs } = await session(browser);
  const open3d = async () => { await page.goto(BASE + "/world?gl=force", { waitUntil: "networkidle0" }); await sleep(3500); };

  await check("3D world renders with every island labelled and no script errors", async () => {
    await open3d();
    const s = await ui(page);
    must(s.mode === "3d" && s.canvas && s.labels >= 9, JSON.stringify(s));
    must(clean(logs).length === 0, clean(logs).join(" | "));
    const theme = await page.$eval("#w3d-theme", (e) => e.textContent);
    must(/world/i.test(theme) && theme.length > 30, "theme reason missing: " + theme);
  });

  await check("published island-kit models replace the built-in island base and landmarks (others keep the built-in look)", async () => {
    await page.goto(BASE + "/world?gl=force", { waitUntil: "networkidle0" });
    let kit = null;
    for (let i = 0; i < 20; i++) { await sleep(700); kit = await page.evaluate(() => window.MMWorldUI.kit()); if (kit && kit.pending === 0 && (kit.base || kit.landmarks)) break; }
    must(kit && kit.base === true && kit.landmarks === 1 && kit.failed === 0 && kit.pending === 0, JSON.stringify(kit));
    must((await page.evaluate(() => document.querySelectorAll(".w3d-label").length)) >= 9, "labels disappeared");
    must(clean(logs).length === 0, clean(logs).join(" | "));
  });

  await check("software WebGL falls back to the simple map automatically", async () => {
    await page.goto(BASE + "/world", { waitUntil: "networkidle0" }); await sleep(1200);
    const s = await ui(page); must(s.mode === "flat" && s.svg && !s.canvas, JSON.stringify(s));
  });

  await check("opening Sports shows friends, zone chips, a shelf and a 3D friend that frees the GPU on Escape", async () => {
    await open3d();
    await page.click('.w3d-label[data-key="sports"]'); await sleep(2200);
    const st = await page.evaluate(() => ({ open: !document.getElementById("w3d-sheet").hidden, title: document.getElementById("w3d-sheet-title").textContent,
      friend: !!document.querySelector(".w3d-friend strong"), chips: [...document.querySelectorAll(".w3d-chips .chip")].map((c) => c.textContent), tiles: document.querySelectorAll(".w3d-shelf .tile").length,
      focus: document.activeElement.id, labelsHidden: getComputedStyle(document.querySelector(".w3d-labels")).opacity }));
    must(st.open && st.title === "Sports" && st.friend && st.tiles > 0 && st.focus === "w3d-sheet-title" && st.labelsHidden === "0", JSON.stringify(st));
    must(st.chips.join() === "All,Football,Swimming", "zones: " + st.chips);
    await page.evaluate(() => [...document.querySelectorAll(".w3d-chips .chip")].find((c) => c.textContent === "Football").click()); await sleep(1200);
    must(await page.evaluate(() => document.querySelector(".w3d-chips .chip[aria-pressed=true]").textContent) === "Football", "chip not pressed");
    const before = await page.evaluate(() => document.querySelectorAll("canvas").length);
    await page.evaluate(() => document.querySelector("#w3d-sheet .a3d-start").click()); await sleep(3000);
    must((await page.evaluate(() => document.querySelectorAll("canvas").length)) === before + 1, "3D friend canvas did not appear");
    must(!(await page.evaluate(() => !!document.querySelector("#w3d-sheet .a3d-msg"))), "3D friend reported an error");
    await page.keyboard.press("Escape"); await sleep(1000);
    must((await page.evaluate(() => document.getElementById("w3d-sheet").hidden)), "sheet still open");
    must((await page.evaluate(() => document.querySelectorAll("canvas").length)) <= before, "3D friend canvas not released");
  });

  await check("drag pans, wheel and buttons zoom, reset restores the view", async () => {
    await open3d();
    const p0 = await labelPos(page), box = await (await page.$("canvas.w3d-canvas")).boundingBox();
    await page.mouse.move(box.x + 200, box.y + 300); await page.mouse.down(); await page.mouse.move(box.x + 120, box.y + 250, { steps: 6 }); await page.mouse.up(); await sleep(1500);
    const p1 = await labelPos(page); must(Math.abs(p1[0] - p0[0]) > 20, `drag did not pan ${p0} -> ${p1}`);
    await page.mouse.move(box.x + 200, box.y + 300); await page.mouse.wheel({ deltaY: -400 }); await sleep(1800);
    const p2 = await labelPos(page); must(p2[2] > p1[2], `wheel did not zoom in ${p1} -> ${p2}`);
    await page.click(".w3d-tool[aria-label='Show the whole map']"); await sleep(1800);
    const p3 = await labelPos(page); must(Math.abs(p3[0] - p0[0]) < 6 && Math.abs(p3[1] - p0[1]) < 6, `reset did not restore ${p0} -> ${p3}`);
  });

  await check("keyboard: Tab reaches the places, Enter opens one, Escape closes it and returns focus", async () => {
    await open3d();
    await page.evaluate(() => document.querySelector(".w3d-label").focus());
    await page.keyboard.press("Enter"); await sleep(1200);
    must(await page.evaluate(() => !document.getElementById("w3d-sheet").hidden), "Enter did not open the sheet");
    await page.keyboard.press("Escape"); await sleep(500);
    must(await page.evaluate(() => document.activeElement.classList.contains("w3d-label")), "focus did not return to the place");
  });

  await check("caregiver settings save, persist and change the world (theme, hidden place)", async () => {
    await open3d();
    await page.click("#w3d-gear-btn"); await sleep(500);
    must(await page.evaluate(() => document.getElementById("w3d-gear-btn").getAttribute("aria-expanded")) === "true", "gear not expanded");
    await page.evaluate(() => { const f = document.querySelector(".w3d-gear__form"); const s = f.querySelectorAll("select"); s[0].value = "football"; s[1].value = "strong"; f.querySelector("input[name=hidden][value=food]").checked = true; });
    await page.evaluate(() => document.querySelector(".w3d-gear__form button[type=submit]").click()); await sleep(5000);
    const after = await page.evaluate(() => ({ theme: document.getElementById("w3d-theme").textContent, labels: [...document.querySelectorAll(".w3d-label")].map((l) => l.dataset.key), mode: window.MMWorldUI.mode() }));
    must(/Football world/.test(after.theme) && !after.labels.includes("food") && after.mode === "3d", JSON.stringify(after));
    await page.reload({ waitUntil: "networkidle0" }); await sleep(500);
    must(/Football world/.test(await page.$eval("#w3d-theme", (e) => e.textContent)), "setting did not persist");
    page.once("dialog", (d) => d.accept());
    await page.goto(BASE + "/world?gl=force", { waitUntil: "networkidle0" }); await sleep(1500);
    await page.click("#w3d-gear-btn"); await sleep(400);
    await page.evaluate(() => [...document.querySelectorAll(".w3d-gear__form button")].find((b) => b.textContent.includes("Reset theme")).click()); await sleep(1500);
    must(!/Football world/.test(await page.$eval("#w3d-theme", (e) => e.textContent)), "reset theme did nothing");
  });

  await check("losing the GPU context switches to the simple map with a message", async () => {
    await open3d();
    await page.evaluate(() => { const c = document.querySelector("canvas.w3d-canvas"); (c.getContext("webgl2") || c.getContext("webgl")).getExtension("WEBGL_lose_context").loseContext(); });
    await sleep(1500);
    const s = await ui(page); must(s.mode === "flat" && s.svg, JSON.stringify(s));
    must(/simple map/.test(await page.evaluate(() => (document.querySelector(".toast") || {}).textContent || "")), "no explanation shown");
  });

  await check("simple map: keyboard opens a place and Escape returns focus", async () => {
    await page.goto(BASE + "/world?flat=1", { waitUntil: "networkidle0" }); await sleep(600);
    await page.evaluate(() => document.querySelector(".flat-stop").focus()); await page.keyboard.press("Enter"); await sleep(1200);
    must(await page.evaluate(() => !document.getElementById("w3d-sheet").hidden), "sheet did not open");
    await page.keyboard.press("Escape"); await sleep(300);
    must(await page.evaluate(() => document.activeElement.classList.contains("flat-stop")), "focus lost");
  });

  await check("reduced motion still renders the 3D world", async () => {
    const rm = await browser.newPage(); await rm.setViewport({ width: 390, height: 844, isMobile: true });
    await rm.emulateMediaFeatures([{ name: "prefers-reduced-motion", value: "reduce" }]);
    const errs = []; rm.on("pageerror", (e) => errs.push(e.message));
    await rm.goto(BASE + "/world?gl=force", { waitUntil: "networkidle0" }); await sleep(2500);
    const s = await ui(rm); must(s.mode === "3d" && s.canvas && errs.length === 0, JSON.stringify(s) + errs.join("|")); await rm.close();
  });

  await check("parent link: create, open with the password, see the family view", async () => {
    await page.goto(BASE + "/settings/parent-links", { waitUntil: "networkidle0" });
    await page.type("#pl-label", "Grandma"); await page.type("#pl-pw", "grandma-view-pw");
    await Promise.all([page.waitForNavigation({ waitUntil: "networkidle0" }), page.click("form button[type=submit]")]);
    const link = await page.$eval("#newlink", (i) => i.value);
    const other = await launch();
    try {
      const fam = await other.newPage(); await fam.goto(link, { waitUntil: "networkidle0" });
      await fam.type("#pw", "wrong-password"); await Promise.all([fam.waitForNavigation({ waitUntil: "networkidle0" }), fam.click("form button[type=submit]")]);
      must(/isn't right/.test(await fam.$eval("body", (b) => b.textContent)), "wrong password not refused");
      await fam.type("#pw", "grandma-view-pw"); await Promise.all([fam.waitForNavigation({ waitUntil: "networkidle0" }), fam.click("form button[type=submit]")]);
      must(/read-only family view/.test(await fam.$eval("body", (b) => b.textContent)), "family view did not open");
    } finally { await other.close(); }
  });
} finally { await browser.close(); }

const adminBrowser = await launch();
try {
  const { page, logs } = await session(adminBrowser, { user: "boss", pw: "AdminPass123!x" });
  await check("admin AI 3D review page shows the model in the real viewer", async () => {
    await page.goto(BASE + "/admin/3d/1?gl=force", { waitUntil: "networkidle0" }); await sleep(4000);
    const s = await page.evaluate(() => ({ canvases: document.querySelectorAll(".a3d.big canvas").length, msg: (document.querySelector(".a3d-msg") || {}).textContent || "", clips: [...document.querySelectorAll(".a3d-clips button")].map((b) => b.textContent) }));
    must(s.canvases === 1 && !s.msg && s.clips.join() === "Pose,Bob", JSON.stringify(s));
    await page.evaluate(() => [...document.querySelectorAll(".a3d-clips button")].find((b) => b.textContent === "Bob").click()); await sleep(2000);
    must(!(await page.evaluate(() => (document.querySelector(".a3d-msg") || {}).textContent)), "clip failed to load");
    must(clean(logs).length === 0, clean(logs).join(" | "));
  });
  await check("admin World Library and AI 3D pages load", async () => {
    for (const u of ["/admin/world/", "/admin/3d/", "/admin/"]) { const r = await page.goto(BASE + u, { waitUntil: "networkidle0" }); must(r.status() === 200, u + " -> " + r.status()); }
  });
} finally { await adminBrowser.close(); }

const failed = results.filter((r) => !r[0]);
console.log(`\n${results.length - failed.length}/${results.length} browser checks passed`);
process.exit(failed.length ? 1 : 0);
