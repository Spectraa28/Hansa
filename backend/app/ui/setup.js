'use strict';
const $ = id => document.getElementById(id);
let csrf = null, inspection = null, pagination = {};
function node(tag, text) { const n = document.createElement(tag); n.textContent = text; return n; }
function message(text, error = false) { $('message').textContent = text; $('message').classList.toggle('error', error); }
async function api(url, method = 'GET', body) {
  const headers = {};
  if (method !== 'GET') {
    if (!csrf) csrf = (await api('/auth/me')).csrf_token;
    headers['X-CSRF-Token'] = csrf;
    headers['Content-Type'] = 'application/json';
  }
  const response = await fetch(url, { method, headers, credentials: 'same-origin', body: body === undefined ? undefined : JSON.stringify(body) });
  const result = response.status === 204 ? null : await response.json();
  if (!response.ok) throw new Error(typeof result.detail === 'string' ? result.detail : 'Request failed. Review the configuration and try again.');
  return result;
}
function action(id, event, fn) {
  $(id).addEventListener(event, async e => {
    e.preventDefault();
    try { await fn(e); } catch (error) { message(error.message, true); }
  });
}
function options(id, items, value, label, append = false) {
  if (!append) $(id).replaceChildren(node('option', 'Select ' + id.replaceAll('-', ' ')));
  if (!append) $(id).firstChild.value = '';
  for (const item of items) { const option = node('option', label(item)); option.value = value(item); $(id).append(option); }
  $(id).disabled = items.length === 0 && $(id).options.length === 1;
}
async function paged(id, endpoint, key, value, label, append = false) {
  const page = append ? (pagination[id] || 1) + 1 : 1;
  const result = await api(endpoint + (endpoint.includes('?') ? '&' : '?') + 'per_page=100&page=' + page);
  pagination[id] = page;
  options(id, result[key], value, label, append);
  let button = $(id + '-more');
  if (!button) {
    button = node('button', 'Load more'); button.id = id + '-more'; button.type = 'button';
    $(id).parentElement.append(button);
  }
  button.hidden = !result.has_next;
  button.onclick = async () => { button.disabled = true; try { await paged(id, endpoint, key, value, label, true); } catch (e) { message(e.message, true); } finally { button.disabled = false; } };
  return result[key];
}
async function session() {
  try {
    const result = await api('/auth/me'); csrf = result.csrf_token;
    $('login').hidden = true; $('account').hidden = false;
    $('signed-in').textContent = 'Signed in as ' + result.user.name;
    await refresh();
  } catch (e) { $('login').hidden = false; $('account').hidden = true; message(e.message, true); }
}
async function refresh() {
  inspection = null; $('review').hidden = true;
  options('installation', [], i => i.id, i => i.account);
  options('repository', [], r => r.id, r => r.full_name);
  options('branch', [], b => b.name, b => b.name);
  $('import-button').disabled = true;
  await paged('imports', '/github/imports', 'imports', r => r.id, r => `${r.repository_name} · ${r.commit_sha.slice(0, 10)} · ${r.status}`);
  $('inspect').disabled = true; $('retrieve').disabled = true;
  const connection = await api('/github/connection');
  $('connection').textContent = 'GitHub connection: ' + connection.status;
  $('grant').hidden = true;
  if (connection.status === 'connected') {
    const result = await api('/github/installations?per_page=100');
    $('grant').href = result.installation_url; $('grant').hidden = false;
    await paged('installation', '/github/installations', 'installations', i => i.id, i => i.account);
  }
}
action('email-login', 'submit', async () => {
  const password = $('password').value; $('password').value = '';
  await api('/auth/login', 'POST', { email: $('email').value, password }); await session();
});
action('signed-in-refresh', 'click', session);
action('refresh', 'click', refresh);
action('connect', 'click', async () => {
  const result = await api('/github/connect', 'POST');
  $('grant').href = result.installation_url; $('grant').hidden = false;
  $('authorization').href = result.authorization_url; $('authorization').hidden = false;
  message('Open Authorize GitHub, approve access, then return here and refresh. Grant repository access if the app is not installed.');
});
action('installation', 'change', async () => {
  options('repository', [], r => r.id, r => r.full_name); options('branch', [], b => b.name, b => b.name); $('import-button').disabled = true;
  if (!$('installation').value) return;
  await paged('repository', '/github/repositories?installation_id=' + $('installation').value, 'repositories', r => r.id, r => r.full_name);
});
action('repository', 'change', async () => {
  $('import-button').disabled = true;
  if (!$('repository').value) return;
  const installation = $('installation').value, repository = $('repository').value;
  const result = await api(`/github/branches?installation_id=${installation}&repository_id=${repository}&per_page=100`);
  if (installation !== $('installation').value || repository !== $('repository').value) return;
  await paged('branch', `/github/branches?installation_id=${installation}&repository_id=${repository}`, 'branches', b => b.name, b => b.name);
  $('branch').value = result.repository.default_branch || ''; $('import-button').disabled = !$('branch').value;
});
action('branch', 'change', async () => { $('import-button').disabled = !$('branch').value; });
action('import-form', 'submit', async () => {
  $('import-button').disabled = true;
  try {
    const result = await api('/github/imports', 'POST', { installation_id: Number($('installation').value), repository_id: Number($('repository').value), branch: $('branch').value });
    await refresh(); $('imports').value = result.id; await importStatus(); message('Import queued. Refresh to check its progress.');
  } finally { $('import-button').disabled = !$('branch').value; }
});
async function importStatus() {
  $('review').hidden = true; inspection = null;
  $('inspect').disabled = true; $('retrieve').disabled = true;
  if (!$('imports').value) return;
  const result = await api('/github/imports/' + $('imports').value);
  $('import-status').textContent = `${result.status} · ${result.commit_sha}` + (result.failure_reason ? ' · ' + result.failure_reason : '');
  $('inspect').disabled = result.status !== 'ready'; $('retrieve').disabled = result.status !== 'ready';
}
action('imports', 'change', importStatus);
function checkboxes(id, values, selected = []) {
  $(id).replaceChildren();
  for (const value of values) {
    const label = node('label', ''); const input = document.createElement('input'); input.type = 'checkbox'; input.value = value; input.checked = selected.includes(value);
    label.append(input, document.createTextNode(value)); $(id).append(label);
  }
  if (!values.length) $(id).append(node('p', 'None detected. Absence of a finding does not prove absence of integrations.'));
}
function render(result) {
  inspection = result; $('review').hidden = false;
  const scan = result.findings, confirmed = result.configuration;
  $('scan-summary').textContent = `${scan.scanned_files} files read · ${scan.scanned_bytes} bytes · ${scan.partial ? 'Incomplete scan: review skipped content before later execution.' : 'Static inspection complete within limits.'}`;
  $('issues').replaceChildren();
  for (const conflict of scan.conflicts) $('issues').append(node('p', `${conflict.kind}: ${conflict.values.join(', ')}. ${conflict.reason}`));
  if (scan.missing.length) $('issues').append(node('p', 'Missing: ' + scan.missing.join(', ')));
  if (scan.warnings.length) $('issues').append(node('p', 'Inspection notices: ' + scan.warnings.join(', ')));
  $('findings').replaceChildren();
  for (const finding of scan.findings) {
    const row = document.createElement('tr');
    for (const text of [finding.kind, finding.value, finding.source_file + ' · ' + finding.location, finding.confidence]) row.append(node('td', text));
    $('findings').append(row);
  }
  $('config-fields').replaceChildren();
  for (const [key, title] of [['python_version', 'Python version or constraint'], ['entrypoint', 'Entrypoint'], ['model_provider', 'Model provider'], ['model_id', 'Model ID']]) {
    const values = [...new Set(scan.findings.filter(f => f.kind === key).map(f => f.value))];
    const label = node('label', title), input = document.createElement(key === 'model_provider' ? 'select' : 'input');
    input.id = 'config-' + key; input.required = true;
    if (key === 'model_provider') {
      for (const provider of ['', 'openai', 'anthropic', 'google', 'aws_bedrock', 'litellm']) { const option = node('option', provider || 'Choose a provider'); option.value = provider; input.append(option); }
    } else {
      input.type = 'text'; input.maxLength = key === 'entrypoint' ? 180 : key === 'python_version' ? 80 : 120;
      const list = document.createElement('datalist'); list.id = 'choices-' + key;
      for (const value of values) { const option = document.createElement('option'); option.value = value; list.append(option); }
      input.setAttribute('list', list.id); label.append(list);
    }
    input.value = confirmed?.[key] || (values.length === 1 ? values[0] : ''); label.append(input); $('config-fields').append(label);
  }
  const manifests = [...new Set(scan.findings.filter(f => f.kind === 'dependency_manifest').map(f => f.value))];
  checkboxes('manifests', manifests, confirmed?.dependency_manifests || (manifests.length === 1 ? manifests : []));
  $('no-manifests').hidden = manifests.length > 0;
  checkboxes('tools', [...new Set(scan.findings.filter(f => f.kind === 'tool').map(f => f.value))], confirmed?.approved_tools || []);
  $('confirmation').textContent = result.status === 'confirmed' ? 'Configuration saved. Execution is not enabled.' : 'Configuration awaits confirmation.';
}
async function inspect(method) {
  const id = $('imports').value; if (!id) return;
  $('inspect').disabled = true; $('retrieve').disabled = true; message(method === 'POST' ? 'Inspecting source…' : 'Retrieving findings…');
  try {
    const result = await api(`/github/imports/${id}/inspection`, method);
    if (id === $('imports').value) { render(result); message('Findings loaded. Review evidence and permissions.'); }
  } finally { if (id === $('imports').value) { $('inspect').disabled = false; $('retrieve').disabled = false; } }
}
action('inspect', 'click', () => inspect('POST'));
action('retrieve', 'click', () => inspect('GET'));
action('configuration', 'submit', async () => {
  if (!inspection || inspection.import_id !== $('imports').value) throw new Error('Retrieve findings for the selected import first.');
  const body = { revision: inspection.revision, commit_sha: inspection.commit_sha,
    dependency_manifests: [...$('manifests').querySelectorAll('input:checked')].map(i => i.value),
    approved_tools: [...$('tools').querySelectorAll('input:checked')].map(i => i.value) };
  for (const key of ['python_version', 'entrypoint', 'model_provider', 'model_id']) body[key] = $('config-' + key).value.trim();
  render(await api(`/github/imports/${inspection.import_id}/configuration`, 'POST', body)); message('Configuration and explicit tool permissions saved.');
});
session();
