const form = document.querySelector('#check-form');
const brandInput = document.querySelector('#brand');
const domainInput = document.querySelector('#domain');
const promptsInput = document.querySelector('#prompts');
const providerList = document.querySelector('#provider-list');
const promptCount = document.querySelector('#prompt-count');
const formError = document.querySelector('#form-error');
const submitButton = document.querySelector('#submit-button');
const buttonText = document.querySelector('#button-text');
const emptyState = document.querySelector('#empty-state');
const loadingState = document.querySelector('#loading-state');
const report = document.querySelector('#report');
const results = document.querySelector('#results');

function readPrompts() {
  return promptsInput.value.split(/\r?\n/).map((line) => line.trim()).filter(Boolean);
}

function showError(message) {
  formError.textContent = message;
  formError.hidden = !message;
}

function setLoading(active) {
  submitButton.disabled = active;
  buttonText.textContent = active ? 'Проверяем…' : 'Проверить бренд';
  loadingState.hidden = !active;
  if (active) { emptyState.hidden = true; report.hidden = true; }
}

async function loadProviders() {
  try {
    const response = await fetch('/api/providers');
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || 'Не удалось загрузить подключения');
    providerList.replaceChildren();
    for (const connection of data) {
      const label = document.createElement('label');
      label.className = `provider-option ${connection.configured ? '' : 'unconfigured'}`;
      const input = document.createElement('input');
      input.type = 'checkbox';
      input.name = 'provider_ids';
      input.value = connection.id;
      input.disabled = !connection.configured;
      input.checked = connection.configured && (connection.id === 'gigachat' || !providerList.querySelector('input:checked'));
      const name = document.createElement('strong');
      name.textContent = connection.name;
      const status = document.createElement('span');
      status.textContent = connection.configured ? connection.model : 'Нужен API-ключ';
      label.append(input, name, status);
      providerList.append(label);
    }
  } catch (error) {
    providerList.textContent = error.message || 'Не удалось загрузить подключения';
  }
}

function renderReport(data) {
  document.querySelector('#report-subtitle').textContent = `Бренд: ${data.brand}`;
  document.querySelector('#report-context').textContent = data.domain ? `Сайт для контекста: ${data.domain}` : 'Сайт не указан';
  results.replaceChildren();
  for (const check of data.checks) {
    const group = document.createElement('section');
    group.className = 'provider-report';
    const title = document.createElement('h3');
    title.textContent = check.provider_name;
    const summary = document.createElement('p');
    summary.className = 'provider-summary';
    summary.textContent = `Упоминаний: ${check.summary.mentioned} из ${check.summary.successful} успешных · Ошибок: ${check.summary.failed}`;
    group.append(title, summary);
    for (const item of check.results) {
      const card = document.createElement('article');
      card.className = 'result-card';
      const top = document.createElement('div');
      top.className = 'result-top';
      const prompt = document.createElement('h4');
      prompt.textContent = item.prompt;
      const badge = document.createElement('span');
      badge.className = `badge ${item.error ? 'badge-error' : item.mentioned ? 'badge-hit' : 'badge-miss'}`;
      badge.textContent = item.error ? 'Ошибка' : item.mentioned ? 'Бренд упомянут' : 'Нет упоминания';
      top.append(prompt, badge);
      const label = document.createElement('p');
      label.className = 'answer-label';
      label.textContent = item.error ? 'ПРИЧИНА' : 'ОТВЕТ МОДЕЛИ';
      const answer = document.createElement('p');
      answer.className = 'answer-text';
      answer.textContent = item.error || item.answer || '';
      card.append(top, label, answer);
      group.append(card);
    }
    results.append(group);
  }
  report.hidden = false;
}

promptsInput.addEventListener('input', () => {
  const count = readPrompts().length;
  promptCount.textContent = `${count} / 20`;
  promptCount.classList.toggle('over-limit', count > 20);
});

form.addEventListener('submit', async (event) => {
  event.preventDefault();
  showError('');
  const brand = brandInput.value.trim();
  const domain = domainInput.value.trim();
  const prompts = readPrompts();
  const provider_ids = [...providerList.querySelectorAll('input:checked')].map((input) => input.value);
  if (!provider_ids.length || provider_ids.length > 5) return showError('Выберите от 1 до 5 настроенных моделей');
  if (!brand) return showError('Укажите название бренда');
  if (!prompts.length) return showError('Добавьте хотя бы один вопрос');
  if (prompts.length > 20) return showError('За один раз можно проверить не более 20 вопросов');
  if (prompts.some((prompt) => prompt.length > 500)) return showError('Каждый вопрос должен быть не длиннее 500 символов');
  setLoading(true);
  try {
    const response = await fetch('/api/check', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ brand, domain, prompts, provider_ids }) });
    const data = await response.json();
    if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : 'Не удалось выполнить проверку');
    renderReport(data);
  } catch (error) {
    showError(error.message || 'Не удалось выполнить проверку');
    emptyState.hidden = false;
  } finally { setLoading(false); }
});

loadProviders();
