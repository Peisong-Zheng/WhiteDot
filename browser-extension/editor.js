"use strict";

// Editor text and ranges use DOM UTF-16 offsets. The desktop protocol uses Unicode code points.
const WhiteDotEditor = (() => {
  const sensitiveName = /password|passcode|passwd|secret|api.?key|credit.?card|card.?number|security.?code|one.?time|(?:^|[\W_])(?:cvv|cvc|otp|ccnum|pin)(?:[\W_]|$)|验证码|密钥|密码|银行卡/i;
  const sensitiveToken = /(?:^|\s)(?:current-password|new-password|one-time-code|cc-\S+|webauthn)(?:$|\s)/i;
  const credential = /\b(?:sk-[\w-]{16,}|gh[pousr]_[\w]{24,}|github_pat_[\w]{24,}|AIza[\w-]{30,}|AKIA[A-Z0-9]{16})\b|-----BEGIN [A-Z ]*PRIVATE KEY-----|\b(?:authorization\s*:\s*bearer|(?:api[_ -]?key|password|access[_ -]?token)\s*[:=])\s*["']?[\w+/.=-]{8,}/i;
  const block = new Set(["DIV", "P", "LI", "UL", "OL", "PRE", "BLOCKQUOTE", "SECTION", "H1", "H2", "H3", "H4", "H5", "H6"]);
  function focused() {
    let el = document.activeElement;
    while (el?.shadowRoot?.activeElement) el = el.shadowRoot.activeElement;
    return el;
  }

  function eligible(el) {
    if (!el || !el.isConnected || el.closest('[inert], [aria-readonly="true"], [aria-disabled="true"]')) return false;
    if (el instanceof HTMLInputElement || el instanceof HTMLTextAreaElement) {
      if (el.matches(":disabled") || el.readOnly || (el instanceof HTMLInputElement && !["text","search"].includes(el.type))) return false;
    } else if (!el.isContentEditable || !el.hasAttribute("contenteditable")) return false;
    const hints = ["id","name","aria-label","placeholder","data-testid","inputmode"].map(k => el.getAttribute(k) || "").join(" ");
    return !sensitiveName.test(hints) && !sensitiveToken.test(el.getAttribute("autocomplete") || "")
      && !["numeric", "decimal", "tel", "email"].includes(el.inputMode)
      && !el.closest('[data-whitedot="off"]')
      && ["none", ""].includes(getComputedStyle(el).webkitTextSecurity || "");
  }

  function snapshot(el) {
    if (!eligible(el)) return null;
    if (el instanceof HTMLInputElement || el instanceof HTMLTextAreaElement) {
      const text = el.value;
      return text.length <= 48000 && [...text].length <= 24000 && !credential.test(text) ? {text} : null;
    }
    let text = "";
    const runs = [];
    // Complex non-text widgets may have a different visible and editable model.
    // Skip them instead of silently folding their labels into the draft.
    if (el.querySelector('[contenteditable="false"], input, textarea, select, button, img, script, style')) return null;
    function visit(parent) {
      let previousBlock = false;
      for (const child of parent.childNodes) {
        if (text.length > 48000) return;
        if (child.nodeType === Node.TEXT_NODE) {
          if (!child.data) continue;
          if (previousBlock && !text.endsWith("\n")) text += "\n";
          runs.push({node: child, start: text.length, end: text.length + child.length});
          text += child.data;
          previousBlock = false;
        } else if (child.nodeType === Node.ELEMENT_NODE) {
          const style = getComputedStyle(child);
          if (child.hidden || style.display === "none" || style.visibility === "hidden") continue;
          if (child.tagName === "BR") {
            text += "\n";
            previousBlock = false;
          } else {
            const nextBlock = block.has(child.tagName);
            if ((previousBlock || nextBlock) && text && !text.endsWith("\n")) text += "\n";
            visit(child);
            previousBlock = nextBlock;
          }
        }
      }
    }
    visit(el);
    return text.length <= 48000 && [...text].length <= 24000 && !credential.test(text) ? {text, runs} : null;
  }

  function offsets(text, issues) {
    const boundaries = [0];
    for (const ch of text) boundaries.push(boundaries.at(-1) + ch.length);
    return issues.slice(0, 128).flatMap(issue => {
      const {start, end, original, suggestions} = issue;
      if (!Number.isInteger(start) || !Number.isInteger(end) || start < 0 || end <= start ||
          end >= boundaries.length || !Array.isArray(suggestions) || !suggestions.some(w => typeof w === "string")) return [];
      const a = boundaries[start], b = boundaries[end];
      return text.slice(a, b) === original ? [{...issue, start: a, end: b}] : [];
    });
  }

  function richRange(view, start, end) {
    const left = view.runs.find(r => r.start <= start && start < r.end);
    const right = view.runs.find(r => r.start < end && end <= r.end);
    if (!left || !right) return null;
    const range = new Range();
    range.setStart(left.node, start - left.start);
    range.setEnd(right.node, end - right.start);
    return range.toString() === view.text.slice(start, end) ? range : null;
  }

  function replace(el, expected, issue, value) {
    const view = snapshot(el);
    if (focused() !== el || !view || view.text !== expected || view.text.slice(issue.start, issue.end) !== issue.original) return false;
    if (!view.runs) {
      const {scrollLeft, scrollTop} = el;
      const before = new InputEvent("beforeinput", {bubbles: true, composed: true, cancelable: true, inputType: "insertReplacementText", data: value});
      if (!el.dispatchEvent(before) || focused() !== el || el.value !== expected || !eligible(el)) return false;
      // Bypass framework value trackers, then notify the framework through input.
      const proto = el instanceof HTMLTextAreaElement ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
      Object.getOwnPropertyDescriptor(proto, "value").set.call(el, expected.slice(0, issue.start) + value + expected.slice(issue.end));
      el.setSelectionRange(issue.start + value.length, issue.start + value.length);
      el.scrollLeft = scrollLeft;
      el.scrollTop = scrollTop;
      el.dispatchEvent(new InputEvent("input", {bubbles: true, composed: true, inputType: "insertReplacementText", data: value}));
      return true;
    }
    const range = richRange(view, issue.start, issue.end);
    if (!range) return false;
    const selection = el.getRootNode().getSelection?.() || document.getSelection();
    selection.removeAllRanges();
    selection.addRange(range);
    // Chromium's native edit command preserves surrounding markup and undo history.
    return document.execCommand("insertText", false, value);
  }

  // Build one text mirror per paint pass, shared by every suggestion.
  function mirror(el, text, shadow) {
    const rect = el.getBoundingClientRect(), style = getComputedStyle(el);
    if (!el.offsetWidth || !el.offsetHeight || style.writingMode !== "horizontal-tb") return null;
    const div = document.createElement("div");
    for (const property of ["font","fontFamily","fontSize","fontWeight","fontStyle","fontStretch","fontVariant","fontKerning","fontFeatureSettings","fontVariantLigatures","letterSpacing","wordSpacing","lineHeight","textAlign","textIndent","textTransform","direction","unicodeBidi","tabSize","wordBreak","overflowWrap","paddingTop","paddingRight","paddingBottom","paddingLeft"]) {
      div.style[property] = style[property];
    }
    Object.assign(div.style, {position:"fixed", visibility:"hidden", pointerEvents:"none", boxSizing:"border-box",
      left:rect.left + "px", top:rect.top + "px", border:"0", margin:"0", overflow:"hidden",
      width:el.clientWidth + "px", height:el.clientHeight + "px", transformOrigin:"top left"});
    const sx = rect.width / el.offsetWidth, sy = rect.height / el.offsetHeight;
    div.style.left = (rect.left + el.clientLeft * sx) + "px";
    div.style.top = (rect.top + el.clientTop * sy) + "px";
    div.style.transform = "scale(" + sx + "," + sy + ")";
    if (el instanceof HTMLInputElement) {
      div.style.whiteSpace = "pre";
      div.style.lineHeight = Math.max(1, el.clientHeight - parseFloat(style.paddingTop) - parseFloat(style.paddingBottom)) + "px";
    } else {
      div.style.whiteSpace = el.wrap === "off" ? "pre" : "pre-wrap";
      div.style.overflowWrap = el.wrap === "off" ? "normal" : "break-word";
    }
    const node = document.createTextNode(text);
    div.append(node, document.createTextNode("\u200b"));
    shadow.append(div);
    div.scrollTop = el.scrollTop;
    div.scrollLeft = el.scrollLeft;
    return {div, node};
  }
  return {focused, eligible, snapshot, offsets, richRange, replace, mirror};
})();
