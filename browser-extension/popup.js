"use strict";
const input = document.querySelector("#code");
const status = document.querySelector("#status");
const ready = chrome.storage.local.setAccessLevel({accessLevel: "TRUSTED_CONTEXTS"});
ready.then(() => chrome.storage.local.get("pairingCode")).then(({pairingCode}) => {
  status.textContent = pairingCode ? "已保存配对码。" : "等待配对。";
});
document.querySelector("form").addEventListener("submit", async event => {
  event.preventDefault();
  const value = input.value.trim();
  if (!/^[A-Za-z0-9_-]{32,128}$/.test(value)) {
    status.textContent = "请粘贴完整的桌面配对码。";
    return;
  }
  await ready;
  await chrome.storage.local.set({pairingCode: value});
  input.value = "";
  status.textContent = "已保存。回到网页并点入英文输入框即可校对。";
});
document.querySelector("#forget").addEventListener("click", async () => {
  await ready;
  await chrome.storage.local.remove("pairingCode");
  input.value = "";
  status.textContent = "已解除配对。";
});
