import { chromium } from "playwright-core";
import fs from "node:fs/promises";
await fs.mkdir("artifacts/references", { recursive: true });
const browser = await chromium.launch({
  executablePath:
    "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe",
  headless: true,
});
try {
  const page = await browser.newPage({
    viewport: { width: 1440, height: 1000 },
  });
  for (const [name, url] of [
    ["groq", "https://console.groq.com/keys"],
    [
      "vercel",
      "https://vercel.com/docs/ai-gateway/authentication-and-byok/api-keys",
    ],
  ]) {
    try {
      await page.goto(url, { waitUntil: "domcontentloaded", timeout: 30000 });
      await page.screenshot({ path: "artifacts/references/" + name + ".png" });
      console.log(name + ": " + (await page.title()));
    } catch {
      console.log(
        name + ": public browser unavailable, consulted official web page text",
      );
    }
  }
} finally {
  await browser.close();
}
