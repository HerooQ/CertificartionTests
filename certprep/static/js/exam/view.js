/** Rendering for the in-progress exam (question, options, navigator, timer). */

import { $, el } from './dom.js';

const LOW_TIME_SECONDS = 300;

export function renderTimer(secondsLeft) {
  const minutes = Math.floor(secondsLeft / 60);
  const seconds = String(secondsLeft % 60).padStart(2, '0');
  const timer = $('timer');
  timer.textContent = `${minutes}:${seconds}`;
  timer.classList.toggle('low', secondsLeft <= LOW_TIME_SECONDS);
}

export function buildNavigator(count, onSelect) {
  const grid = $('grid');
  grid.replaceChildren(
    ...Array.from({ length: count }, (_, index) =>
      el('button', {
        type: 'button',
        class: 'gcell',
        text: String(index + 1),
        ariaLabel: `Go to question ${index + 1}`,
        onclick: () => onSelect(index),
      }),
    ),
  );
}

function refreshNavigator(state) {
  [...$('grid').children].forEach((cell, index) => {
    const classes = ['gcell'];
    if (state.isAnswered(index)) classes.push('answered');
    if (state.flags[index]) classes.push('flagged');
    if (index === state.current) classes.push('current');
    cell.className = classes.join(' ');
  });
}

/** Paint the current question and all progress indicators. */
export function renderQuestion(state, onChoose) {
  const { paper, current } = state;
  const question = paper[current];

  $('qcount').textContent = `Question ${current + 1} of ${paper.length}`;
  $('qmeta').textContent = question.domain + (question.multi ? '  ·  select all that apply' : '');
  $('qtext').textContent = question.question;

  const chosen = state.answers[current] ?? [];
  $('options').replaceChildren(
    ...question.options.map((option) => {
      const selected = chosen.includes(option.text);
      const input = el('input', {
        type: question.multi ? 'checkbox' : 'radio',
        name: 'option',
        checked: selected,
        onchange: () => onChoose(option.text),
      });
      return el('label', { class: `opt${selected ? ' sel' : ''}` }, input, el('span', { text: option.text }));
    }),
  );

  const flagButton = $('flag-btn');
  flagButton.classList.toggle('on', Boolean(state.flags[current]));
  flagButton.setAttribute('aria-pressed', String(Boolean(state.flags[current])));
  $('next-btn').textContent = current === paper.length - 1 ? 'Finish →' : 'Next →';
  $('progress-bar').style.width = `${((current + 1) / paper.length) * 100}%`;
  $('answered-count').textContent = String(state.answeredCount());
  refreshNavigator(state);
}

/** Ask a yes/no question in the modal dialog. Resolves true when confirmed. */
export function confirmDialog(message) {
  const overlay = $('confirm-overlay');
  const ok = $('confirm-ok');
  const cancel = $('confirm-cancel');
  $('confirm-msg').textContent = message;
  overlay.classList.add('show');
  ok.focus();
  return new Promise((resolve) => {
    const finish = (result) => {
      overlay.classList.remove('show');
      ok.onclick = cancel.onclick = null;
      resolve(result);
    };
    ok.onclick = () => finish(true);
    cancel.onclick = () => finish(false);
  });
}
