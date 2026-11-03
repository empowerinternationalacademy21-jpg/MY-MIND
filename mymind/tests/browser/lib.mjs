import chromium from "@sparticuz/chromium";
import puppeteer from "puppeteer-core";
export const BASE = "http://127.0.0.1:" + (process.env.PORT || "5055");
export async function launch() {
  const exe = await chromium.executablePath();
  return puppeteer.launch({ executablePath: exe, headless: "shell", args: [...chromium.args, "--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--ignore-gpu-blocklist", "--enable-webgl"] });
}
export async function session(browser, { w = 390, h = 844, user = "mum", pw = "Sup3rSecret!pw", mobile = true } = {}) {
  const page = await browser.newPage();
  await page.setViewport({ width: w, height: h, deviceScaleFactor: 1, isMobile: mobile, hasTouch: mobile });
  const logs = [];
  page.on("console", (m) => { if (["error", "warning"].includes(m.type())) logs.push(m.type() + ": " + m.text()); });
  page.on("pageerror", (e) => logs.push("PAGEERROR: " + e.message));
  page.on("requestfailed", (r) => logs.push("REQFAIL: " + r.url() + " " + (r.failure() || {}).errorText));
  page.on("response", (r) => { if (r.status() >= 400) logs.push("HTTP " + r.status() + ": " + r.url()); });
  await page.goto(BASE + "/login", { waitUntil: "networkidle0" });
  if (await page.$("#username")) {
    await page.type("#username", user); await page.type("#password", pw);
    await Promise.all([page.waitForNavigation({ waitUntil: "networkidle0" }), page.click("button[type=submit]")]);
  }
  return { page, logs };
}
export const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
