// Browser-independent UI behavior tests. These do not claim visual browser coverage.
const {test} = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const path = require('node:path');
const script = fs.readFileSync(path.join(__dirname, '../src/incident_demo/operator/static/app.js'), 'utf8');

function harness(config = {mode:'cloud', examples:[]}) {
  const elements = new Map(), calls = [];
  class Element {
    constructor() { this.childNodes=[]; this.value=''; this.checked=false; this.disabled=false; }
    append(...nodes) { this.childNodes.push(...nodes); }
    replaceChildren(...nodes) { this.childNodes = nodes; }
    click() { return this.onclick?.(); }
    focus() { this.focused = true; }
    reset() { for (const id of ['hash-confirm','reason']) get(id).value=''; for (const id of ['facts-reviewed','citations-reviewed']) get(id).checked=false; }
    set innerHTML(_) { throw Error('Untrusted HTML must never be interpreted'); }
  }
  const get = id => { if (!elements.has(id)) elements.set(id, new Element()); return elements.get(id); };
  let responder = async () => config;
  const context = vm.createContext({document:{getElementById:get, createElement:()=>new Element(), querySelector:()=>({content:'page-token'})},
    fetch: async (url, options) => {calls.push({url,options}); return {ok:true,json:()=>responder(url,options)};},
    setInterval:()=>0, setTimeout:()=>0, clearTimeout:()=>{}, crypto:{randomUUID:()=> 'fixed-key'},
    window:{confirm:()=>true}, Blob, URL, console});
  vm.runInContext(script, context);
  return {get,calls,context,eval:code=>vm.runInContext(code,context),respond:fn=>{responder=fn;}};
}
const run = {run_id:'p07-'+'a'.repeat(40), status:'awaiting_approval', investigation:{result:{investigation:{facts:[]},evidence:[]}},
  proposal:{proposal_hash:'b'.repeat(64), action:'rollback_demo_release', expected_current_release:'release-42',
    arguments:{service_id:'checkout-api',target_release:'release-41'}, expires_at:'2099-01-01T00:00:00Z',evidence_ids:[]}};
function select(h, value=run, live=true) {h.eval(`selected=${JSON.stringify({run:value,provenance:'test'})};live=${live};render();`);}
function acknowledge(h) {h.get('hash-confirm').value=run.proposal.proposal_hash;h.get('reason').value='Reviewed';h.get('facts-reviewed').checked=true;h.get('citations-reviewed').checked=true;h.eval('updateDecision()');}

test('approval requires exact hash, both acknowledgments and fresh authority', () => {
  const h=harness();select(h);assert.equal(h.get('approve').disabled,true);acknowledge(h);assert.equal(h.get('approve').disabled,false);
  h.get('hash-confirm').value='c'.repeat(64);h.eval('updateDecision()');assert.equal(h.get('approve').disabled,true);
  select(h,{...run,proposal:{...run.proposal,expires_at:'2000-01-01T00:00:00Z'}});acknowledge(h);assert.equal(h.get('approve').disabled,true);
  select(h,{...run,status:'rejected'});acknowledge(h);assert.equal(h.get('approve').disabled,true);
});
test('recorded examples never expose executable approval', () => {
  const h=harness();select(h,run,false);acknowledge(h);assert.equal(h.get('decision-form').hidden,true);assert.equal(h.get('approve').disabled,true);
});
test('model content is rendered as text, including malicious markup', () => {
  const h=harness(), attack='<img src=x onerror=alert(1)>';
  const value={...run,investigation:{result:{investigation:{facts:[{statement:attack,evidence_ids:['obs-1']}]},evidence:[]}}};
  select(h,value);assert.equal(h.get('findings').childNodes[0].childNodes[0].textContent,attack);
});
test('decision sends the reviewed hash once, then clears review acknowledgments', async () => {
  const h=harness();await new Promise(setImmediate);select(h);acknowledge(h);
  h.respond(async(url,options)=>options.method==='POST'?{decision:'approved'}:{...run,status:'resolved'});
  await h.eval('decide("approved")');
  const decisions=h.calls.filter(c=>c.options.method==='POST');assert.equal(decisions.length,1);
  const body=JSON.parse(decisions[0].options.body);assert.equal(body.proposal_hash,run.proposal.proposal_hash);assert.equal(body.facts_reviewed,true);
  assert.equal(h.get('facts-reviewed').checked,false);assert.equal(h.get('approve').disabled,true);
});
test('canceling confirmation submits no decision', async () => {
  const h=harness();await new Promise(setImmediate);select(h);acknowledge(h);h.context.window.confirm=()=>false;
  await h.eval('decide("approved")');assert.equal(h.calls.filter(c=>c.options.method==='POST').length,0);
});
test('switching runs immediately removes prior approval authority', async () => {
  const h=harness();await new Promise(setImmediate);select(h);acknowledge(h);
  h.respond(()=>new Promise(()=>{}));h.eval(`openRun('p07-${'c'.repeat(40)}')`);
  assert.equal(h.get('approve').disabled,true);assert.equal(h.get('decision-form').hidden,true);
});

test('recorded evidence button opens the preselected first model case', async () => {
  const h=harness({mode:'replay',examples:[{id:'resolved',label:'Recorded control: resolved'},{id:'case-001',label:'Recorded model investigation: case-001'}]});
  await new Promise(setImmediate);
  assert.equal(h.get('examples').value,'case-001');
  assert.equal(h.get('load-example').disabled,false);
  h.respond(async()=>({label:'Recorded model investigation: case-001',provenance:'Saved model evidence',run:{...run,status:'recorded_investigation'}}));
  await h.get('load-example').click();
  assert.equal(h.calls.at(-1).url,'/api/examples/case-001');
  assert.equal(h.get('run-reference').textContent,run.run_id);
  assert.match(h.get('notice').textContent,/case-001/);
  assert.equal(h.get('decision-form').hidden,true);
});
test('empty saved selection gives guidance instead of silently doing nothing', async () => {
  const h=harness();await new Promise(setImmediate);h.get('examples').value='';
  const before=h.calls.length;await h.get('load-example').click();
  assert.equal(h.calls.length,before);assert.match(h.get('notice').textContent,/Choose a saved walkthrough/);
  assert.equal(h.get('examples').focused,true);
});
test('failed evidence request shows an error and restores the open button', async () => {
  const h=harness({mode:'replay',examples:[{id:'resolved',label:'Resolved'}]});await new Promise(setImmediate);
  assert.equal(h.get('examples').value,'resolved');
  h.respond(async()=>{throw Error('Evidence request failed');});
  await h.get('load-example').click();
  assert.equal(h.get('notice').textContent,'Evidence request failed');
  assert.equal(h.get('load-example').disabled,false);
  assert.equal(h.get('load-example').textContent,'Open recorded evidence');
});
