"use strict";

const endpoint = "http://127.0.0.1:37831/v1/sync";
const browser = /Edg\//.test(navigator.userAgent) ? "edge" : "chrome";
const trustedStorage = chrome.storage.local.setAccessLevel({accessLevel: "TRUSTED_CONTEXTS"});

async function handle(message, sender) {
  if (sender.id !== chrome.runtime.id || !sender.tab) return {active: false};
  await trustedStorage;
  const {pairingCode} = await chrome.storage.local.get("pairingCode");
  if (message.kind === "ready") return {paired: Boolean(pairingCode)};
  const {field, text, clear} = message;
  if (!pairingCode || message.kind !== "sync" || !/^[A-Za-z0-9_-]{1,128}$/.test(field)) {
    return {active: false};
  }
  if (!clear) {
    if (!sender.tab.active || typeof text !== "string" || text.length > 48000 || [...text].length > 24000) {
      return {active: false};
    }
    const window = await chrome.windows.get(sender.tab.windowId);
    if (!window.focused) return {active: false};
  }
  const payload = clear ? {browser, field, clear: true} : {browser, field, text};
  const response = await fetch(endpoint, {
    method: "POST",
    headers: {"Content-Type": "application/json", "Authorization": "Bearer " + pairingCode},
    body: JSON.stringify(payload),
    cache: "no-store", credentials: "omit", redirect: "error",
    signal: AbortSignal.timeout(2400)
  });
  if (!response.ok) return {active: false, unavailable: true};
  return response.json();
}

chrome.runtime.onMessage.addListener((message, sender, respond) => {
  if (!message || !["ready", "sync"].includes(message.kind)) return false;
  handle(message, sender).then(respond, () => respond({active: false, unavailable: true}));
  return true;
});

chrome.storage.onChanged.addListener(async (changes, area) => {
  if (area === "local" && changes.pairingCode) {
    const tabs = await chrome.tabs.query({});
    await Promise.allSettled(tabs.filter(t => t.id !== undefined)
      .map(t => chrome.tabs.sendMessage(t.id, {kind: "pairingChanged"})));
  }
});
