#!/usr/bin/env node
/**
 * Screenshot helper driven over the Chrome DevTools Protocol.
 *
 * The plain `--screenshot` flag clamps the window to 500 CSS px and captures
 * mid-transition, which is useless for checking a responsive layout. This
 * drives a real headless Chrome, sets an exact viewport, waits for the page to
 * settle and then captures either the viewport or the full page.
 *
 *   node tools/shot.mjs --url http://127.0.0.1:8765/ --out shot.png \
 *        --width 1440 --height 1000 [--full] [--wait 1600] [--motion]
 *
 * Requires only Node (global fetch + WebSocket).
 */

import { spawn } from "node:child_process";
import { mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";

const args = process.argv.slice(2);
function option(name, fallback) {
  const index = args.indexOf(`--${name}`);
  if (index === -1) return fallback;
  const value = args[index + 1];
  return value && !value.startsWith("--") ? value : true;
}

const url = option("url", "http://127.0.0.1:8765/");
const out = option("out", "shot.png");
const width = Number(option("width", 1440));
const height = Number(option("height", 1000));
const fullPage = Boolean(option("full", false));
const wait = Number(option("wait", 1400));
const allowMotion = Boolean(option("motion", false));
const evalScript = option("eval", "");
const scrollTo = option("scroll", "");
const grantClipboard = Boolean(option("clipboard", false));
const clicks = option("click", "")
  .toString()
  .split(",")
  .map((value) => value.trim())
  .filter(Boolean);

const port = 9333 + Math.floor(Math.random() * 400);
const profile = mkdtempSync(join(tmpdir(), "fmg-shot-"));

const chrome = spawn(
  CHROME,
  [
    "--headless=new",
    `--remote-debugging-port=${port}`,
    `--user-data-dir=${profile}`,
    "--no-first-run",
    "--no-default-browser-check",
    "--hide-scrollbars",
    "--disable-extensions",
    "--mute-audio",
    "about:blank",
  ],
  { stdio: "ignore" }
);

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

async function findPageTarget() {
  for (let attempt = 0; attempt < 80; attempt += 1) {
    try {
      const response = await fetch(`http://127.0.0.1:${port}/json/list`);
      const targets = await response.json();
      const page = targets.find((target) => target.type === "page");
      if (page && page.webSocketDebuggerUrl) return page.webSocketDebuggerUrl;
    } catch (error) {
      /* Chrome is still starting. */
    }
    await sleep(120);
  }
  throw new Error("Chrome did not expose a page target");
}

function connect(wsUrl) {
  return new Promise((resolve, reject) => {
    const socket = new WebSocket(wsUrl);
    const pending = new Map();
    let nextId = 1;

    socket.addEventListener("message", (event) => {
      const message = JSON.parse(event.data);
      if (message.id && pending.has(message.id)) {
        const { resolve: done, reject: fail } = pending.get(message.id);
        pending.delete(message.id);
        if (message.error) fail(new Error(JSON.stringify(message.error)));
        else done(message.result);
      }
    });
    socket.addEventListener("error", reject);
    socket.addEventListener("open", () => {
      resolve({
        send(method, params = {}) {
          const id = nextId;
          nextId += 1;
          return new Promise((done, fail) => {
            pending.set(id, { resolve: done, reject: fail });
            socket.send(JSON.stringify({ id, method, params }));
          });
        },
        close() {
          socket.close();
        },
      });
    });
  });
}

try {
  const client = await connect(await findPageTarget());

  await client.send("Page.enable");
  await client.send("Runtime.enable");
  await client.send("Emulation.setDeviceMetricsOverride", {
    width,
    height,
    deviceScaleFactor: 1,
    mobile: width < 760,
  });
  await client.send("Emulation.setEmulatedMedia", {
    features: [
      {
        name: "prefers-reduced-motion",
        value: allowMotion ? "no-preference" : "reduce",
      },
      {
        name: "prefers-reduced-transparency",
        value: "no-preference",
      },
    ],
  });

  await client.send("Page.navigate", { url });
  await sleep(wait);

  if (scrollTo) {
    await client.send("Runtime.evaluate", {
      expression: `document.querySelector(${JSON.stringify(
        scrollTo
      )}).scrollIntoView({block: "start", behavior: "instant"})`,
    });
    await sleep(1200);
  }

  if (grantClipboard) {
    await client.send("Browser.grantPermissions", {
      origin: new URL(url).origin,
      permissions: ["clipboardReadWrite", "clipboardSanitizedWrite"],
    });
  }

  for (const selector of clicks) {
    await client.send("Runtime.evaluate", {
      expression: `(() => {
        const el = document.querySelector(${JSON.stringify(selector)});
        if (!el) return "missing";
        el.click();
        return "clicked";
      })()`,
      awaitPromise: true,
      userGesture: true,
    });
    await sleep(900);
  }

  if (fullPage) {
    const metrics = await client.send("Page.getLayoutMetrics");
    const size = metrics.cssContentSize || metrics.contentSize;
    await client.send("Emulation.setDeviceMetricsOverride", {
      width,
      height: Math.ceil(size.height),
      deviceScaleFactor: 1,
      mobile: width < 760,
    });
    await sleep(400);
  }

  if (evalScript) {
    const result = await client.send("Runtime.evaluate", {
      expression: evalScript.toString(),
      awaitPromise: true,
      returnByValue: true,
    });
    console.log("EVAL", JSON.stringify(result.result && result.result.value));
  }

  const shot = await client.send("Page.captureScreenshot", {
    format: "png",
    captureBeyondViewport: fullPage,
    fromSurface: true,
  });

  writeFileSync(out, Buffer.from(shot.data, "base64"));
  console.log(`${out} ${width}x${fullPage ? "full" : height}`);
  client.close();
} finally {
  chrome.kill("SIGKILL");
  await sleep(250);
  try {
    rmSync(profile, { recursive: true, force: true, maxRetries: 5 });
  } catch (error) {
    /* Chrome may still hold files; the temp dir is harmless. */
  }
}
