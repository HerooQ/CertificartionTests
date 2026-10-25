/** Results report page: filtering, manual entry, import, deletion, auto-refresh. */

const REFRESH_MS = 10000;
const AUTO_REFRESH_KEY = 'report_autorefresh';

const $ = (id) => document.getElementById(id);
const state = JSON.parse($('report-state').textContent);

async function postJson(url, payload) {
  const response = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  return response.json();
}

const reportUrl = (test) => (test ? `/report?test=${encodeURIComponent(test)}` : '/report');

// -- filter / print ------------------------------------------------------
$('testfilter').addEventListener('change', (e) => {
  location.href = reportUrl(e.target.value);
});
$('print-btn').addEventListener('click', () => window.print());

// -- deletion --------------------------------------------------------------
document.addEventListener('click', async (event) => {
  const button = event.target.closest('[data-delete-id]');
  if (!button) return;
  if (!confirm('Delete this attempt permanently? This cannot be undone.')) return;
  try {
    const result = await postJson('/api/delete', { id: Number(button.dataset.deleteId) });
    if (result.ok) location.reload();
    else alert('Delete failed.');
  } catch {
    alert('Delete failed — is the server running?');
  }
});

$('delete-all-btn').addEventListener('click', async () => {
  const { shownCount, selectedTest } = state;
  if (shownCount === 0) {
    alert('There are no attempts to delete.');
    return;
  }
  const what = selectedTest
    ? `all ${shownCount} attempts for '${selectedTest}'`
    : `ALL ${shownCount} attempts across every test`;
  if (!confirm(`Delete ${what}? This cannot be undone.`)) return;
  if (!confirm(`Are you sure? This permanently removes ${what}.`)) return;
  try {
    const result = await postJson('/api/delete', { all: true, test: selectedTest });
    if (result.ok) location.href = reportUrl(selectedTest);
    else alert('Delete failed.');
  } catch {
    alert('Delete failed — is the server running?');
  }
});

// -- manual add ------------------------------------------------------------
$('add-form').addEventListener('submit', async (event) => {
  event.preventDefault();
  const message = $('a_msg');
  const correct = Number.parseInt($('a_correct').value, 10);
  const total = Number.parseInt($('a_total').value, 10);
  const first = $('a_first').value.trim();
  const surname = $('a_surname').value.trim();
  const test = $('a_test').value;

  if (!test) return void (message.textContent = 'Choose a test.');
  if (!first || !surname) return void (message.textContent = 'Enter first name and surname.');
  if (Number.isNaN(correct) || Number.isNaN(total) || total <= 0 || correct < 0 || correct > total) {
    return void (message.textContent = 'Check correct/total (0 ≤ correct ≤ total).');
  }

  message.textContent = 'Saving…';
  try {
    const result = await postJson('/api/add', {
      test, first_name: first, surname, correct, total, comments: $('a_comments').value,
    });
    if (result.ok) location.reload();
    else message.textContent = `Save failed: ${result.error ?? 'unknown error'}`;
  } catch {
    message.textContent = 'Save failed — is the server running?';
  }
});

// -- spreadsheet import ----------------------------------------------------
$('import-form').addEventListener('submit', async (event) => {
  event.preventDefault();
  const message = $('imp_msg');
  const file = $('imp_file').files[0];
  if (!file) return void (message.textContent = 'Choose a file first.');

  const defaultTest = $('imp_test').value;
  const query = defaultTest ? `?test=${encodeURIComponent(defaultTest)}` : '';
  message.textContent = 'Importing…';
  try {
    const response = await fetch(`/api/import${query}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/octet-stream' },
      body: await file.arrayBuffer(),
    });
    const result = await response.json();
    if (!result.ok) {
      message.textContent = `Import failed: ${result.error ?? 'unknown format'}`;
      return;
    }
    message.textContent = `Imported ${result.imported}${result.skipped ? ` — skipped ${result.skipped}` : ''}.`;
    if (result.errors?.length) console.info('Import skipped:', result.errors);
    setTimeout(() => location.reload(), 1000);
  } catch {
    message.textContent = 'Import failed — is the server running?';
  }
});

// -- auto-refresh (paused while the user is editing) ----------------------
const autoRefresh = {
  get enabled() {
    try {
      return localStorage.getItem(AUTO_REFRESH_KEY) !== '0';
    } catch {
      return true;
    }
  },
  set enabled(value) {
    try {
      localStorage.setItem(AUTO_REFRESH_KEY, value ? '1' : '0');
    } catch {
      /* storage unavailable */
    }
  },
};

const checkbox = $('autochk');
checkbox.checked = autoRefresh.enabled;
checkbox.addEventListener('change', () => (autoRefresh.enabled = checkbox.checked));

function userIsBusy() {
  if ([...document.querySelectorAll('details.addbox')].some((box) => box.open)) return true;
  if (/^(INPUT|SELECT|TEXTAREA)$/.test(document.activeElement?.tagName ?? '')) return true;
  return String(window.getSelection?.() ?? '') !== '';
}

setInterval(() => {
  if (autoRefresh.enabled && !userIsBusy()) location.reload();
}, REFRESH_MS);
