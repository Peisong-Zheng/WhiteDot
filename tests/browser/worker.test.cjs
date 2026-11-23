const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const test = require("node:test");

function worker({paired=true, focused=true}={}) {
  const requests = [];
  let listener, access;
  const chrome = {
    runtime: {id:"fixture", onMessage:{addListener(fn){ listener=fn; }}},
    storage: {local: {async setAccessLevel(cfg) { access=cfg.accessLevel; },
      async get() { return {pairingCode: paired ? "fictional-pairing-value" : ""}; }},
      onChanged:{addListener(){}}},
    windows: {async get() { return {focused}; }}
  };
  vm.runInNewContext(fs.readFileSync(path.resolve(__dirname,"../../browser-extension/worker.js"),"utf8"), {
    chrome, navigator:{userAgent:"Fixture Edg/126"}, AbortSignal,
    fetch:async (url,options)=>{ requests.push({url,options});return {ok:true,json:async()=>({active:true,issues:[]})}; }
  });
  async function send(msg,tab={id:7,active:true,windowId:1}) {
    return new Promise(resolve=>listener({kind:"sync",field:"fixture",...msg},{id:"fixture",tab},resolve));
  }
  return {send,requests,access};
}

test("trusted storage, authenticated local-only request and explicit Edge identity",async()=>{
  const w=worker();
  assert.equal(w.access,"TRUSTED_CONTEXTS");
  assert.equal((await w.send({kind:"ready"})).paired,true);
  assert.equal((await w.send({text:"Synthetic writing."})).active,true);
  assert.equal(w.requests.length,1);
  const {url,options}=w.requests[0];
  assert.equal(url,"http://127.0.0.1:37831/v1/sync");
  assert.equal(options.headers.Authorization,"Bearer fictional-pairing-value");
  assert.equal(options.redirect,"error");
  assert.deepEqual(JSON.parse(options.body),{browser:"edge",field:"fixture",text:"Synthetic writing."});
});
test("unpaired, hidden, unfocused and oversized sources do not transmit",async()=>{
  for (const [config,msg,tab] of [[{paired:false},{text:"a"}],[{focused:false},{text:"a"}],[{},{text:"a"},{id:7,active:false}],[{},{text:"😀".repeat(24001)}]]) {
    const w=worker(config);
    assert.equal((await w.send(msg,tab)).active,false);
    assert.equal(w.requests.length,0);
  }
});
test("blur expires only the named field, even after window deactivation",async()=>{
  const w=worker({focused:false});
  await w.send({clear:true,text:"never forward"});
  assert.deepEqual(JSON.parse(w.requests[0].options.body),{browser:"edge",field:"fixture",clear:true});
});
