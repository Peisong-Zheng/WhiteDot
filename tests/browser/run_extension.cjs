// End-to-end pairing and one actual marker click over an isolated debugger pipe.
// Run with a Chromium build that supports Extensions.loadUnpacked.
const fs = require("node:fs");
const path = require("node:path");
const os = require("node:os");
const http = require("node:http");
const {spawn} = require("node:child_process");
const {once} = require("node:events");

const root = path.resolve(__dirname, "../..");
const chrome = process.env.CHROME_BIN || "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
const python = process.env.PYTHON || path.join(root,".venv/bin/python");
const wait = ms => new Promise(resolve => setTimeout(resolve,ms));
const profile = fs.mkdtempSync(path.join(os.tmpdir(),"whitedot-browser-"));
const fixture = http.createServer((req,res) => {
  res.writeHead(200,{"Content-Type":"text/html; charset=utf-8","Cache-Control":"no-store"});
  res.end('<!doctype html><meta charset=utf-8><title>WhiteDot test</title><input style="margin:80px;font:22px monospace;width:340px" autofocus value="😀 fix teh word">');
});
let browser, bridge;
let id = 0, buffer = "";
const callbacks = new Map();
async function cdp(method, params={}, sessionId) {
  const message = {id:++id, method, params, sessionId};
  const response = new Promise((resolve,reject) => callbacks.set(message.id,{resolve,reject}));
  browser.stdio[3].write(JSON.stringify(message)+"\0");
  return response;
}
async function tab(url) {
  const {targetId} = await cdp("Target.createTarget",{url});
  const {sessionId} = await cdp("Target.attachToTarget",{targetId,flatten:true});
  await cdp("Target.activateTarget",{targetId});
  await cdp("Page.bringToFront",{},sessionId);
  return sessionId;
}
async function evaluate(session,expression) {
  const r=await cdp("Runtime.evaluate",{expression,returnByValue:true},session);
  return r.result.value;
}
async function until(check, label) {
  for(let i=0;i<65;i++) {
    const result=await check();
    if(result) return result;
    await wait(100);
  }
  throw new Error("Timed out waiting for "+label);
}
function find(node,predicate){
  if(predicate(node)) return node;
  for (const child of [...(node.children||[]),...(node.shadowRoots||[])]) {
    const found=find(child,predicate);
    if(found) return found;
  }
}
async function click(session, predicate, label) {
  const node = await until(async()=>{
    const {root}=await cdp("DOM.getDocument",{depth:-1,pierce:true},session);
    return find(root,predicate);
  },label);
  const {model}=await cdp("DOM.getBoxModel",{nodeId:node.nodeId},session);
  const box=model.border, x=(box[0]+box[4])/2,y=(box[1]+box[5])/2;
  for(const type of ["mousePressed","mouseReleased"]) await cdp("Input.dispatchMouseEvent",
    {type,x,y,button:"left",clickCount:1},session);
}

async function main(){
  bridge=spawn(python,[path.join(__dirname,"loopback_fixture.py")],{cwd:root,stdio:["ignore","pipe","inherit"]});
  await Promise.race([once(bridge.stdout,"data"),once(bridge,"exit").then(()=>{throw Error("Could not start fixture bridge on port 37831");})]);
  fixture.listen(0,"127.0.0.1");await once(fixture,"listening");
  browser=spawn(chrome,["--headless=new","--remote-debugging-pipe","--enable-unsafe-extension-debugging",
    "--disable-sync","--disable-gpu","--no-first-run","--no-default-browser-check","--disable-background-networking","--user-data-dir="+profile,"about:blank"],
    {stdio:["ignore","ignore","ignore","pipe","pipe"]});
  browser.stdio[4].setEncoding("utf8");
  browser.stdio[4].on("data", s=>{
    buffer+=s;
    let end;
    while((end=buffer.indexOf("\0"))!==-1){
      const msg=JSON.parse(buffer.slice(0,end));buffer=buffer.slice(end+1);
      const cb=callbacks.get(msg.id);
      if(cb){callbacks.delete(msg.id);if(msg.error)cb.reject(Error(msg.error.message));else cb.resolve(msg.result);}
    }
  });
  const extension=await cdp("Extensions.loadUnpacked",{path:path.join(root,"browser-extension")});
  const popup=await tab("chrome-extension://"+extension.id+"/popup.html");
  await until(()=>evaluate(popup,'document.querySelector("#status")?.textContent === "等待配对。"'),"pairing popup");
  await evaluate(popup,'document.querySelector("#code").value="local-integration-fixture-no-actual-account";document.querySelector("form").requestSubmit();true');
  try {
    await until(()=>evaluate(popup,'document.querySelector("#status").textContent.includes("回到网页")'),"saved pairing");
  } catch (e) {
    throw Error(e.message+" ("+await evaluate(popup,'JSON.stringify([document.querySelector("#status").textContent,typeof chrome.storage,document.querySelector("#code").validity.valid])')+")");
  }
  const session=await tab("http://127.0.0.1:"+fixture.address().port+"/");
  await until(()=>evaluate(session,'document.querySelector("input")?.value==="😀 fix teh word"'),"fixture page");
  await evaluate(session,'document.querySelector("input").focus();true');
  await click(session,n=>n.nodeName==="BUTTON" && n.attributes?.includes("mark"),"live red underline");
  await click(session,n=>n.nodeName==="BUTTON" && n.children?.some(c=>c.nodeValue==="the"),"suggestion card");
  await until(()=>evaluate(session,'document.querySelector("input").value==="😀 fix the word"'),"corrected field");
  console.log("PASS: actual unpacked MV3 → paired Python loopback → DOM red underline → click-through correction");
}

const timer=setTimeout(()=>{console.error("Integration timeout");process.exitCode=1;browser?.kill();bridge?.kill();fixture.close();},30000);
main().catch(e=>{console.error(e.message);process.exitCode=1;}).finally(async()=>{
  clearTimeout(timer);
  if(browser && browser.exitCode===null){const done=once(browser,"exit");browser.kill();await done;}
  if(bridge && bridge.exitCode===null){const done=once(bridge,"exit");bridge.kill();await done;}
  fixture.close();
  fs.rmSync(profile,{recursive:true,force:true,maxRetries:4,retryDelay:100});
});
