"use strict";
const $ = id => document.getElementById(id);
const token = document.querySelector('meta[name="operator-token"]').content;
let selected = null, live = false, busy = false, generation = 0, poll = null;
const terminal = new Set(["resolved", "unresolved", "failed", "expired", "rejected", "escalated"]);
const pretty = value => JSON.stringify(value, null, 2);
function node(tag, text, cls) { const n = document.createElement(tag); n.textContent = text; if (cls) n.className = cls; return n; }
function notice(text, error=false) { $("notice").textContent = text; $("notice").className = error ? "error" : ""; }
async function api(path, body) {
  const response = await fetch(path, {method: body ? "POST" : "GET", cache:"no-store",
    headers: {"X-Operator-Token": token, ...(body ? {"Content-Type":"application/json"} : {})},
    ...(body ? {body: JSON.stringify(body)} : {})});
  const result = await response.json();
  if (!response.ok) throw new Error(result.error === "cloud_unavailable_or_outcome_unknown"
    ? "Cloud request could not be confirmed. Check AWS sign-in, then refresh the run. For intake, retry the SAME incident key."
    : `Request rejected (${response.status}). No approval is implied. Check status before retrying.`);
  return result;
}
function references(parent, ids) { for (const id of ids || []) parent.append(node("span", id, "citation")); }
function resetDecision() { $("decision-form").reset(); }
function updateDecision() {
  const run = selected?.run, p = run?.proposal;
  const valid = live && !busy && run?.status === "awaiting_approval" && p &&
    Date.parse(p.expires_at) > Date.now() && selected.run.investigation &&
    $("hash-confirm").value === p.proposal_hash && $("reason").value.trim() &&
    $("facts-reviewed").checked && $("citations-reviewed").checked;
  $("approve").disabled = !valid; $("reject").disabled = !valid;
}
function render() {
  const run = selected.run, response = run.investigation || {}, result = response.result || response;
  const investigation = result.investigation || {};
  $("run-title").textContent = "Checkout API · incident review";
  $("status").textContent = run.status.replaceAll("_", " ").toUpperCase();
  $("provenance").textContent = selected.provenance;
  $("run-reference").textContent = run.run_id;
  $("refresh").disabled = !live || busy; $("export").disabled = false;
  $("raw").textContent = pretty(selected);
  $("timeline").replaceChildren();
  for (const event of run.history || []) { const item = node("li", event.status.replaceAll("_", " ")); item.append(node("time", event.at)); $("timeline").append(item); }
  const findings = $("findings"); findings.replaceChildren();
  if (investigation.justification) findings.append(node("p", investigation.justification));
  for (const fact of investigation.facts || []) { const item = node("div", "", "finding"); item.append(node("p", fact.statement)); references(item, fact.evidence_ids); findings.append(item); }
  if (investigation.hypotheses?.length) findings.append(node("h3", "Hypotheses"));
  for (const h of investigation.hypotheses || []) { const item = node("div", "", "finding"); item.append(node("p", `${h.status}: ${h.cause}`)); references(item, h.supporting_evidence); if (h.contradicting_evidence?.length) { item.append(node("p", "Contradicting evidence")); references(item, h.contradicting_evidence); } findings.append(item); }
  if (investigation.missing_information?.length) { findings.append(node("h3", "Missing information")); for (const missing of investigation.missing_information) findings.append(node("p", typeof missing === "string" ? missing : pretty(missing))); }
  if (investigation.next_check) { findings.append(node("h3", "Next check"), node("p", investigation.next_check)); }
  if (!findings.childNodes.length) findings.append(node("p", live ? "Investigation evidence is not yet available. Refresh to check progress." : "This retained control demonstrates workflow behavior; it is not model reasoning.", "muted"));
  const evidence = $("evidence"); evidence.replaceChildren();
  for (const e of result.evidence || []) { const item = document.createElement("details"); item.append(node("summary", `${e.evidence_id} · ${e.source} · ${e.complete ? "complete" : "incomplete"}`), node("p", `Collected ${e.collected_at} / ${e.source_version}`, "hint"), node("pre", pretty(e.payload))); evidence.append(item); }
  if (!evidence.childNodes.length) evidence.append(node("p", "No source passages in this view. Inspect the retained record below.", "muted"));
  const proposal = $("proposal"); proposal.replaceChildren();
  if (run.proposal) { const p = run.proposal; proposal.append(node("h3", `${p.action}: ${p.expected_current_release} → ${p.arguments.target_release}`), node("p", `Service: ${p.arguments.service_id} · Expires: ${p.expires_at}`), node("p", p.proposal_hash, "mono")); references(proposal, p.evidence_ids); }
  else proposal.append(node("p", "No executable proposal. An investigation recommendation alone cannot authorize an action.", "muted"));
  $("decision-form").hidden = !(live && run.status === "awaiting_approval" && run.proposal && run.investigation);
  const verification = $("verification"); verification.replaceChildren();
  const messages = {resolved:"Independent verification recorded recovery of the synthetic service.", unresolved:"The workflow could not confirm recovery. An action receipt alone does not prove health.", rejected:"Proposal rejected. No rollback was authorized.", expired:"Approval expired. No late approval can authorize this proposal.", escalated:"Investigation escalated for human follow-up. No rollback was authorized.", failed:"Workflow failed. Inspect the retained evidence before attempting a new incident."};
  verification.append(node("p", messages[run.status] || (live ? "Waiting for a terminal result and independent verification." : "Recorded evidence only. This view cannot execute actions.")));
  if (run.verification) { verification.append(node("h3", "Independent verification artifact"), node("pre", pretty(run.verification))); }
  if (selected.verification_record) verification.append(node("pre", pretty(selected.verification_record)));
  if (selected.receipt) { verification.append(node("h3", "Recorded synthetic action receipt"), node("pre", pretty(selected.receipt))); }
  updateDecision();
}
function stopPolling() { clearTimeout(poll); poll = null; }
function schedulePoll() { stopPolling(); if (live && selected && !terminal.has(selected.run.status)) poll = setTimeout(() => refresh().catch(showError), 5000); }
function showError(error) { stopPolling(); notice(error.message, true); }
async function refresh() {
  if (!live || !selected || busy) return;
  const g = generation, id = selected.run.run_id;
  const run = await api(`/api/runs/${id}`);
  if (g !== generation) return;
  if (run.proposal?.proposal_hash !== selected.run.proposal?.proposal_hash || run.status !== selected.run.status) resetDecision();
  selected.run = run; render(); schedulePoll();
}
async function openRun(id) {
  if (!/^p07-[a-f0-9]{40}$/.test(id)) throw new Error("Enter the complete p07 run ID.");
  const g = ++generation; stopPolling(); live = false; resetDecision(); updateDecision(); $("decision-form").hidden = true;
  const run = await api(`/api/runs/${id}`);
  if (g !== generation) return;
  live = true; selected = {provenance: run.scenario?.startsWith("control-") ? "Cloud control-test record · synthetic proposal, not model reasoning" : "Live AWS workflow · Nova Lite / V1 · synthetic checkout service · signed operator API", run}; render(); schedulePoll(); notice("Cloud record loaded. Review the evidence before any decision.");
}
$("load-example").onclick = async () => {
  const id = $("examples").value;
  if (!id) { notice("Choose a saved walkthrough from the list, then click Open recorded evidence."); $("examples").focus(); return; }
  const button = $("load-example");
  button.disabled = true; button.textContent = "Opening evidence…";
  try {
    const g = ++generation; stopPolling(); live = false; resetDecision(); updateDecision(); $("decision-form").hidden = true;
    notice("Loading the selected recorded evidence…");
    const example = await api(`/api/examples/${id}`);
    if (g !== generation) return;
    selected = example; render(); notice(`${example.label} · read-only · no AWS calls or actions.`);
  } catch (e) { showError(e); }
  finally { button.disabled = false; button.textContent = "Open recorded evidence"; }
};
$("open-run").onclick = () => openRun($("run-id").value.trim()).catch(showError);
$("refresh").onclick = () => refresh().catch(showError);
$("new-key").onclick = () => { $("intake-key").value = `demo-${crypto.randomUUID()}`; };
$("start").onclick = async () => {
  if (busy) return; busy = true; $("start").disabled = true;
  try { const run = await api("/api/incidents", {idempotency_key:$("intake-key").value.trim()}); $("run-id").value = run.run_id; await openRun(run.run_id); notice("Investigation accepted. Status refreshes every five seconds."); }
  catch (e) { showError(e); } finally { busy = false; $("start").disabled = false; if (selected) render(); schedulePoll(); }
};
async function decide(decision) {
  if (busy || $(decision === "approved" ? "approve" : "reject").disabled) return;
  const id = selected.run.run_id, hash = selected.run.proposal.proposal_hash;
  if (!window.confirm(`${decision === "approved" ? "Approve the synthetic rollback" : "Reject this proposal"}?\nRun: ${id}\nHash: ${hash}`)) return;
  busy = true; updateDecision(); stopPolling();
  try { await api(`/api/runs/${id}/decision`, {proposal_hash:hash, decision, reason:$("reason").value.trim(), facts_reviewed:$("facts-reviewed").checked, citations_reviewed:$("citations-reviewed").checked}); resetDecision(); notice("Decision accepted. The workflow will validate it and report the result."); }
  catch (e) { showError(e); } finally { busy = false; updateDecision(); await refresh().catch(showError); }
}
$("approve").onclick = () => decide("approved"); $("reject").onclick = () => decide("rejected");
$("decision-form").onsubmit = e => e.preventDefault(); $("decision-form").oninput = updateDecision;
$("export").onclick = () => { const url = URL.createObjectURL(new Blob([pretty(selected)+"\n"], {type:"application/json"})); const a = document.createElement("a"); a.href = url; a.download = `${selected.run.run_id}-review.json`; a.click(); setTimeout(() => URL.revokeObjectURL(url), 1000); };
setInterval(updateDecision, 1000);
api("/api/config").then(config => {
  $("connection").textContent = config.mode === "cloud" ? "Cloud bridge connected" : "Saved evidence · offline";
  $("cloud-controls").hidden = config.mode !== "cloud";
  for (const e of config.examples) { const option = node("option", e.label); option.value = e.id; $("examples").append(option); }
  const initial = config.examples.find(e => e.id === "case-001") || config.examples[0];
  $("examples").value = initial?.id || "";
  $("load-example").disabled = !initial;
  $("load-example").textContent = "Open recorded evidence";
  notice(initial ? "A saved walkthrough is selected. Click Open recorded evidence to view it." : "No saved walkthroughs are available in this checkout.");
  if (config.mode === "cloud") $("new-key").click();
}).catch(error => { $("connection").textContent = "Connection unavailable"; $("load-example").textContent = "Saved walkthroughs unavailable"; showError(error); });
