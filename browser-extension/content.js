"use strict";

(() => {
  const editor = WhiteDotEditor;
  let session, paired = false, composing = false, layer, shadow, marks, card;
  let wakeTimer, paintFrame, sequence = 0;
  const newId = () => Array.from(crypto.getRandomValues(new Uint8Array(12)), b => b.toString(16).padStart(2, "0")).join("");
  async function message(data) {
    try { return await chrome.runtime.sendMessage(data); }
    catch { return {active:false, unavailable:true}; }
  }
  const visible = () => document.visibilityState === "visible" && document.hasFocus();

  function removeLayer() {
    cancelAnimationFrame(paintFrame);
    layer?.remove();
    layer = shadow = marks = card = null;
  }
  function clear() {
    clearTimeout(wakeTimer);
    if (session) void message({kind:"sync", field:session.id, clear:true});
    session = null;
    removeLayer();
  }
  function installLayer() {
    if (layer?.isConnected) return;
    layer = document.createElement("div");
    layer.style.cssText = "all:initial!important;position:fixed!important;left:0!important;top:0!important;width:0!important;height:0!important;z-index:2147483647!important;pointer-events:none!important;display:block!important";
    shadow = layer.attachShadow({mode:"closed"});
    const style = document.createElement("style");
    style.textContent = [
      "*{box-sizing:border-box} .mark{position:fixed;pointer-events:auto;cursor:pointer;background:none;border:0;border-bottom:2px solid #d4384a;padding:0;margin:0;height:5px;min-width:1px}",
      ".card{position:fixed;pointer-events:auto;background:#fff;color:#183026;box-shadow:0 3px 18px #192d2440;border:1px solid #becbc3;border-radius:8px;padding:9px;max-width:min(330px,95vw);font:13px/1.4 system-ui,sans-serif;white-space:normal;overflow-wrap:anywhere;direction:ltr;text-align:left}",
      ".card p{margin:0 0 6px}.card button{font:inherit;color:#1b4938;background:#edf5f1;border:1px solid #adc2b6;border-radius:5px;cursor:pointer;margin:2px;padding:3px 7px}"
    ].join("");
    marks = document.createElement("div");
    shadow.append(style, marks);
    document.documentElement.append(layer);
  }
  function hideCard() { card?.remove(); card = null; }

  function showCard(issue, event, current) {
    hideCard();
    const {el, text} = current;
    if (current !== session || editor.focused() !== el || !visible() || editor.snapshot(el)?.text !== text) return;
    card = document.createElement("div");
    card.className = "card";
    card.setAttribute("role", "dialog");
    card.setAttribute("aria-label", "WhiteDot 校对建议");
    card.addEventListener("pointerdown", e => e.preventDefault());
    const explanation = document.createElement("p");
    explanation.textContent = String(issue.explanation || issue.original);
    card.append(explanation);
    for (const value of issue.suggestions.slice(0,3)) {
      if (typeof value !== "string") continue;
      const choice = document.createElement("button");
      choice.type = "button";
      choice.textContent = value || "删除";
      choice.addEventListener("click", () => {
        if (session === current && !composing && visible()) editor.replace(el, text, issue, value);
        hideCard();
        syncFocus();
      });
      card.append(choice);
    }
    shadow.append(card);
    card.style.left = Math.max(0, Math.min(event.clientX, innerWidth - card.offsetWidth - 4)) + "px";
    card.style.top = Math.max(0, Math.min(event.clientY + 6, innerHeight - card.offsetHeight - 4)) + "px";
  }

  function paint() {
    const current = session;
    if (!current?.issues.length || !visible() || composing) { removeLayer(); return; }
    const {el, text, issues} = current;
    const view = editor.snapshot(el);
    if (editor.focused() !== el || view?.text !== text) { removeLayer(); return; }
    installLayer();
    marks.replaceChildren();
    const field = el.getBoundingClientRect();
    const clip = {left:Math.max(0, field.left), top:Math.max(0, field.top),
      right:Math.min(innerWidth,field.right), bottom:Math.min(innerHeight,field.bottom)};
    // The actual field can be partially clipped by a scrolling ancestor.
    for (let parent = el.parentElement; parent; parent = parent.parentElement) {
      const cs = getComputedStyle(parent), r = parent.getBoundingClientRect();
      if (cs.overflowX !== "visible") { clip.left = Math.max(clip.left, r.left); clip.right = Math.min(clip.right, r.right); }
      if (cs.overflowY !== "visible") { clip.top = Math.max(clip.top, r.top); clip.bottom = Math.min(clip.bottom, r.bottom); }
    }
    const mirror = view.runs ? null : editor.mirror(el, text, shadow);
    if (!view.runs && !mirror) return;
    const fragment = document.createDocumentFragment();
    for (const issue of issues) {
      let range;
      if (view.runs) range = editor.richRange(view, issue.start, issue.end);
      else {
        range = new Range();
        range.setStart(mirror.node, issue.start);
        range.setEnd(mirror.node, issue.end);
      }
      if (!range) continue;
      for (const rect of range.getClientRects()) {
        const left = Math.max(rect.left,clip.left), right = Math.min(rect.right,clip.right);
        const bottom = rect.bottom;
        if (right <= left || bottom < clip.top + 2 || bottom > clip.bottom + 2 || rect.height < 1) continue;
        // Skip geometry obscured by another page surface, such as a modal.
        const root = el.getRootNode();
        const hit = root.elementFromPoint?.((left+right)/2, Math.max(clip.top, bottom-3));
        if (hit && hit !== el && !el.contains(hit) && hit !== layer) continue;
        const line = document.createElement("button");
        line.className = "mark"; line.type = "button"; line.tabIndex = -1;
        line.setAttribute("aria-label", "查看 " + issue.original + " 的建议");
        Object.assign(line.style,{left:left+"px", top:(bottom-4)+"px", width:(right-left)+"px"});
        line.addEventListener("pointerdown", e => e.preventDefault());
        line.addEventListener("click", e => {e.stopPropagation(); showCard(issue, e, current);});
        fragment.append(line);
      }
    }
    mirror?.div.remove();
    marks.append(fragment);
  }

  function schedulePaint() {
    if (!session?.issues.length) return;
    cancelAnimationFrame(paintFrame);
    paintFrame = requestAnimationFrame(paint);
  }
  function wake(delay) { clearTimeout(wakeTimer); wakeTimer = setTimeout(pulse, delay); }

  async function pulse() {
    const current = session;
    if (!current || current.pending) return;
    if (!visible() || composing || editor.focused() !== current.el) { syncFocus(); return; }
    const view = editor.snapshot(current.el);
    if (!view) { clear(); return; }
    const revision = current.revision;
    const text = view.text;
    current.pending = true;
    const response = await message({kind:"sync",field:current.id,text});
    current.pending = false;
    if (current !== session) return;
    if (revision !== current.revision || editor.focused() !== current.el || !visible() ||
        editor.snapshot(current.el)?.text !== text) { syncFocus(); return; }
    current.text = text;
    current.issues = response?.active && Array.isArray(response.issues) ? editor.offsets(text,response.issues) : [];
    paint();
    wake(response?.unavailable ? 4000 : 700);
  }
  function syncFocus() {
    const el = editor.focused();
    if (!paired || !visible() || composing || !editor.eligible(el)) { clear(); return; }
    const view = editor.snapshot(el);
    if (!view) { clear(); return; }
    if (session?.el !== el) {
      clear();
      session = {id:newId(), el, text:view.text, revision:0, issues:[], pending:false};
    } else if (session.text !== view.text) {
      session.text = view.text;
      session.revision++;
      session.issues = [];
      removeLayer();
    }
    wake(100);
  }
  async function refreshPairing() {
    const version = ++sequence;
    const state = await message({kind:"ready"});
    if (version !== sequence) return;
    paired = Boolean(state?.paired);
    syncFocus();
  }

  chrome.runtime.onMessage.addListener(m => { if (m.kind === "pairingChanged") void refreshPairing(); });
  window.addEventListener("focus", syncFocus);
  window.addEventListener("blur", clear);
  window.addEventListener("pagehide", clear);
  document.addEventListener("visibilitychange", syncFocus);
  document.addEventListener("focusin", syncFocus, true);
  document.addEventListener("focusout", () => queueMicrotask(syncFocus), true);
  document.addEventListener("input", syncFocus, true);
  document.addEventListener("compositionstart", () => { composing = true; clear(); }, true);
  document.addEventListener("compositionend", () => { composing = false; syncFocus(); }, true);
  document.addEventListener("scroll", schedulePaint, true);
  window.addEventListener("resize", schedulePaint);
  document.addEventListener("pointerdown", e => { if (e.target !== layer) hideCard(); }, true);
  document.addEventListener("keydown", e => { if (e.key === "Escape") hideCard(); }, true);
  void refreshPairing();
})();
