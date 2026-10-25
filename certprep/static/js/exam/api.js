/** Thin wrappers around the server's JSON endpoints. */

async function postJson(url, payload) {
  const response = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  if (!response.ok) throw new Error(`${url} responded ${response.status}`);
  return response.json();
}

export async function fetchQuestions(url) {
  const response = await fetch(url);
  if (!response.ok) throw new Error(`Could not load questions (${response.status})`);
  return response.json();
}

/** Ask the server for the authoritative seconds remaining for this attempt. */
export function syncClock(test, student) {
  return postJson('/api/start', {
    test,
    first_name: student.first,
    surname: student.surname,
  });
}

export function submitResult(test, student, result, comments) {
  return postJson('/api/submit', {
    test,
    first_name: student.first,
    surname: student.surname,
    correct: result.correct,
    total: result.total,
    domains: result.byDomain,
    comments,
  });
}
