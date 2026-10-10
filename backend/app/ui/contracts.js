'use strict';
// Development examples only. No protected evaluation labels or execution controls.
let contractRecord = null, contractReview = false;
function humanRequirement(description, guidance) {
  return { description, verification: 'human_review', rule: null, review_guidance: guidance };
}
function jsonEditor(label, value, className) {
  const wrapper = node('label', label), input = document.createElement('textarea');
  input.className = className; input.rows = 5; input.maxLength = 20000;
  input.value = JSON.stringify(value, null, 2); wrapper.append(input); return wrapper;
}
function inputLabel(label, value, className, maxLength = 2000) {
  const wrapper = node('label', label), input = document.createElement('input');
  input.className = className; input.value = value || ''; input.maxLength = maxLength;
  wrapper.append(input); return wrapper;
}
function addTask(task = { name: '', description: '', input: {}, expected_output: null, required_fields: [], required_facts: [], required_evidence: [], case_kind: 'ordinary', injection_description: null }) {
  if ($('contract-tasks').children.length >= 20) { message('A contract supports at most 20 tasks.', true); return; }
  const fieldset = document.createElement('fieldset');
  fieldset.append(node('legend', 'Representative task'));
  fieldset.append(inputLabel('Task name', task.name, 'task-name', 120), inputLabel('Description', task.description, 'task-description'));
  const label = node('label', 'Case kind'), select = document.createElement('select'); select.className = 'task-kind';
  for (const [value, title] of [['ordinary', 'Ordinary task'], ['injected_failure', 'Explicitly injected failure']]) { const option = node('option', title); option.value = value; select.append(option); }
  select.value = task.case_kind; label.append(select); fieldset.append(label, inputLabel('Injected failure description (only for injected cases)', task.injection_description, 'task-injection'));
  fieldset.append(jsonEditor('JSON input', task.input, 'task-input'), jsonEditor('Expected structured output (null if using required fields)', task.expected_output, 'task-output'));
  fieldset.append(jsonEditor('Required output fields and exact values — automatic checks', task.required_fields, 'task-fields'));
  fieldset.append(node('p', 'Field format: {"pointer":"/status","field_type":"string","check_exact":true,"exact_value":"needs_information"}. These declare checks; nothing is evaluated yet.'));
  fieldset.append(jsonEditor('Required facts', task.required_facts, 'task-facts'), jsonEditor('Required evidence', task.required_evidence, 'task-evidence'));
  fieldset.append(node('p', 'Requirement format: {"description":"…","verification":"human_review","review_guidance":"…"}. For an automatic requirement, use verification "automatic" with a field-rule object in "rule".'));
  const remove = node('button', 'Remove task'); remove.type = 'button'; remove.onclick = () => { fieldset.remove(); invalidateContractReview(); };
  fieldset.append(remove); $('contract-tasks').append(fieldset); invalidateContractReview();
}
function readJSON(input) {
  if (new TextEncoder().encode(input.value).length > 24000) throw new Error('An example JSON editor exceeds its size limit.');
  try { return JSON.parse(input.value); } catch { throw new Error('Fix invalid JSON in ' + input.parentElement.firstChild.textContent + '.'); }
}
function formContract() {
  if (!inspection || inspection.status !== 'confirmed' || !inspection.configuration_revision) throw new Error('Confirm current configuration first.');
  const tasks = [...$('contract-tasks').children].map(f => ({
    name: f.querySelector('.task-name').value, description: f.querySelector('.task-description').value,
    input: readJSON(f.querySelector('.task-input')), expected_output: readJSON(f.querySelector('.task-output')),
    required_fields: readJSON(f.querySelector('.task-fields')), required_facts: readJSON(f.querySelector('.task-facts')),
    required_evidence: readJSON(f.querySelector('.task-evidence')), case_kind: f.querySelector('.task-kind').value,
    injection_description: f.querySelector('.task-injection').value.trim() || null
  }));
  const limits = {};
  for (const key of ['max_runtime_seconds', 'max_model_calls', 'max_tool_calls', 'max_tokens', 'max_spend_usd']) {
    const value = $('limit-' + key).value;
    if (value === '' || !Number.isFinite(Number(value))) throw new Error('Set every execution limit explicitly, including zero where intended.');
    limits[key] = Number(value);
  }
  const body = { base_version: contractRecord?.version || null, configuration_revision: inspection.configuration_revision,
    tasks, acceptable_failures: readJSON($('contract-failures')), protected_behavior: readJSON($('contract-protected')), limits };
  if (new TextEncoder().encode(JSON.stringify(body)).length > 131072) throw new Error('Contract exceeds 128 KiB. Reduce example sizes.');
  return body;
}
function invalidateContractReview() {
  contractReview = false; $('contract-confirm').disabled = true; $('contract-review').hidden = true;
}
function displayContract(record) {
  contractRecord = record; invalidateContractReview();
  $('contract-readiness').textContent = record.version ? `Version ${record.version} · ${record.status}${record.stale ? ' · STALE: configuration changed. Review and save a new version.' : ''}` : 'No saved contract yet.';
  $('contract-missing').replaceChildren();
  for (const requirement of record.missing_requirements || []) $('contract-missing').append(node('li', requirement));
}
function fillContract(content) {
  $('contract-tasks').replaceChildren();
  for (const task of content.tasks || []) addTask(task);
  $('contract-failures').value = JSON.stringify(content.acceptable_failures || { missing_information: null, denied_access: null, tool_failure: null }, null, 2);
  $('contract-protected').value = JSON.stringify(content.protected_behavior || { instructions: null, permissions: null, freshness: null, essential_information: null }, null, 2);
  for (const key of ['max_runtime_seconds', 'max_model_calls', 'max_tool_calls', 'max_tokens', 'max_spend_usd']) $('limit-' + key).value = content.limits?.[key] ?? '';
  invalidateContractReview();
}
async function loadContract() {
  const id = inspection?.import_id;
  if (!id || inspection.status !== 'confirmed') return;
  const record = await api(`/github/imports/${id}/contract`);
  if (inspection?.import_id !== id) return;
  fillContract(record.contract || {}); displayContract(record);
  const history = await api(`/github/imports/${id}/contract/versions?per_page=50`);
  if (inspection?.import_id !== id) return;
  options('contract-history', history.versions, v => v.version, v => `Version ${v.version} · ${v.status}${v.stale ? ' · stale' : ''}`);
  $('contract-history-notice').textContent = history.has_next ? 'Showing the latest 50 versions. Full history remains available through the paginated API.' : '';
}
function contractConfiguration(result) {
  $('contract-section').hidden = false;
  const ready = result.status === 'confirmed' && Boolean(result.configuration_revision);
  $('contract-editor').hidden = !ready;
  $('contract-readiness').textContent = ready ? 'Configuration confirmed. Load or create a development task contract.' : 'Confirm configuration before defining the task contract.';
  contractRecord = null; invalidateContractReview();
  $('contract-missing').replaceChildren();
  $('contract-history').replaceChildren();
  if (ready) loadContract().catch(e => message(e.message, true));
}
action('contract-add-task', 'click', () => addTask());
action('contract-load', 'click', loadContract);
action('contract-template', 'click', () => {
  addTask({ name: 'Illustrative missing order number', description: 'A support agent asks for an order number before looking up an order. Synthetic development example; no customer validation or measured result.',
    input: { message: 'Where is my order?', order_id: null }, expected_output: { status: 'needs_information', missing_fields: ['order_id'] },
    required_fields: [{ pointer: '/status', field_type: 'string', check_exact: true, exact_value: 'needs_information' }],
    required_facts: [humanRequirement('Do not invent order details.', 'Check that the response contains no fabricated order identity or shipment status.')],
    required_evidence: [], case_kind: 'ordinary', injection_description: null });
  message('Added an illustrative task only. Supply your own failure outcomes, protected behavior, and budgets.');
});
action('contract-save', 'click', async () => {
  const id = inspection.import_id;
  const record = await api(`/github/imports/${id}/contract`, 'POST', formContract());
  if (inspection?.import_id !== id) return;
  fillContract(record.contract); displayContract(record); message('New draft version saved. Review the complete saved contract before confirming.');
});
action('contract-review-button', 'click', async () => {
  const id = inspection?.import_id; if (!id) return;
  const record = await api(`/github/imports/${id}/contract`);
  if (inspection?.import_id !== id) return;
  if (!record.version) throw new Error('Save a draft before reviewing.');
  const form = formContract(), stored = record.contract;
  delete form.base_version; delete form.configuration_revision;
  if (JSON.stringify(form) !== JSON.stringify(stored)) throw new Error('Save your current edits before reviewing.');
  displayContract(record); $('contract-review-text').textContent = JSON.stringify(record, null, 2);
  $('contract-review').hidden = false; contractReview = true; $('contract-confirm').disabled = !record.can_confirm;
});
action('contract-confirm', 'click', async () => {
  if (!contractReview || !contractRecord?.can_confirm) throw new Error('Review the saved complete contract first.');
  const record = await api(`/github/imports/${inspection.import_id}/contract/confirm`, 'POST', { version: contractRecord.version, configuration_revision: inspection.configuration_revision });
  displayContract(record); message('Contract confirmed and saved. No execution started; budgets are not enforced yet.');
});
action('contract-history', 'change', async () => {
  if (!$('contract-history').value) return;
  const record = await api(`/github/imports/${inspection.import_id}/contract?version=${$('contract-history').value}`);
  $('contract-history-text').textContent = JSON.stringify(record, null, 2); $('contract-history-review').hidden = false;
});
$('contract-editor').addEventListener('input', invalidateContractReview);
session();
