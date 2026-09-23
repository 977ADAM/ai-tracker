const list = document.querySelector('#connections');
const form = document.querySelector('#connection-form');
const formError = document.querySelector('#form-error');
const settingsError = document.querySelector('#settings-error');
const cancel = document.querySelector('#cancel-edit');
let connections = [];
let editing = null;

function showMessage(node, message) { node.textContent = message; node.hidden = !message; }

async function loadConnections() {
  try {
    const response = await fetch('/api/providers');
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || 'Не удалось загрузить подключения');
    connections = data;
    list.replaceChildren();
    for (const connection of data) {
      const card = document.createElement('article');
      card.className = 'connection-card';
      const title = document.createElement('h3');
      title.textContent = connection.name;
      const info = document.createElement('p');
      info.textContent = `${connection.model} · ${connection.configured ? 'Готово к проверке' : 'Нужен API-ключ'}`;
      const actions = document.createElement('div');
      actions.className = 'connection-actions';
      const edit = document.createElement('button');
      edit.type = 'button'; edit.className = 'secondary-button'; edit.textContent = 'Настроить';
      edit.addEventListener('click', () => editConnection(connection));
      actions.append(edit);
      if (['gigachat', 'deepseek'].includes(connection.id) && connection.configured) {
        const reset = document.createElement('button');
        reset.type = 'button'; reset.className = 'text-button'; reset.textContent = 'Сбросить ключ';
        reset.addEventListener('click', () => resetKey(connection));
        actions.append(reset);
      } else if (!['gigachat', 'deepseek'].includes(connection.id)) {
        const remove = document.createElement('button');
        remove.type = 'button'; remove.className = 'text-button'; remove.textContent = 'Удалить';
        remove.addEventListener('click', () => removeConnection(connection));
        actions.append(remove);
      }
      card.append(title, info, actions);
      list.append(card);
    }
    showMessage(settingsError, '');
  } catch (error) { showMessage(settingsError, error.message || 'Не удалось загрузить подключения'); }
}

function resetForm() {
  editing = null; form.reset();
  document.querySelector('#form-title').textContent = 'Добавить подключение';
  for (const id of ['connection-name', 'endpoint', 'model']) document.getElementById(id).disabled = false;
  document.querySelector('#scope-field').hidden = true;
  cancel.hidden = true;
  showMessage(formError, '');
}

function editConnection(connection) {
  editing = connection.id;
  document.querySelector('#form-title').textContent = `Настроить ${connection.name}`;
  document.querySelector('#connection-name').value = connection.name;
  document.querySelector('#endpoint').value = connection.endpoint || '';
  document.querySelector('#model').value = connection.model;
  document.querySelector('#api-key').value = '';
  const preset = ['gigachat', 'deepseek'].includes(connection.id);
  for (const id of ['connection-name', 'endpoint', 'model']) document.getElementById(id).disabled = preset;
  document.querySelector('#scope-field').hidden = connection.id !== 'gigachat';
  if (connection.scope) document.querySelector('#scope').value = connection.scope;
  cancel.hidden = false;
  showMessage(formError, '');
  form.scrollIntoView({ behavior: 'smooth', block: 'start' });
}

async function removeConnection(connection) {
  if (!confirm(`Удалить подключение «${connection.name}» и его ключ?`)) return;
  try {
    const response = await fetch(`/api/providers/${encodeURIComponent(connection.id)}`, { method: 'DELETE' });
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || 'Не удалось удалить подключение');
    if (editing === connection.id) resetForm();
    await loadConnections();
  } catch (error) { showMessage(settingsError, error.message || 'Не удалось удалить подключение'); }
}

async function resetKey(connection) {
  if (!confirm(`Удалить сохранённый ключ «${connection.name}»? Если ключ задан через переменную среды, подключение останется активным.`)) return;
  try {
    const response = await fetch(`/api/providers/${encodeURIComponent(connection.id)}`, { method: 'DELETE' });
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || 'Не удалось сбросить ключ');
    if (editing === connection.id) resetForm();
    await loadConnections();
  } catch (error) { showMessage(settingsError, error.message || 'Не удалось сбросить ключ'); }
}

form.addEventListener('submit', async (event) => {
  event.preventDefault();
  showMessage(formError, '');
  const key = document.querySelector('#api-key').value;
  let payload;
  if (editing === 'gigachat') payload = { api_key: key, scope: document.querySelector('#scope').value };
  else if (editing === 'deepseek') payload = { api_key: key };
  else payload = {
    name: document.querySelector('#connection-name').value.trim(), kind: 'openai',
    endpoint: document.querySelector('#endpoint').value.trim(), model: document.querySelector('#model').value.trim(), api_key: key,
  };
  try {
    const response = await fetch(editing ? `/api/providers/${encodeURIComponent(editing)}` : '/api/providers', {
      method: editing ? 'PUT' : 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || 'Не удалось сохранить подключение');
    resetForm();
    await loadConnections();
  } catch (error) { showMessage(formError, error.message || 'Не удалось сохранить подключение'); }
});

cancel.addEventListener('click', resetForm);
loadConnections();
