/** Results screen: score banner, per-domain breakdown and answer review. */

import { $, el } from './dom.js';

const SAVE_NOTE_ID = 'save-note';

export function setSaveNote(message) {
  const note = $(SAVE_NOTE_ID);
  if (note) note.textContent = message;
}

function banner(result, config) {
  const { selection, passMark, scaleMax } = config;
  const scoredOnly = selection.strategy === 'planned' ? ' scored' : '';
  return el(
    'div',
    { class: `result-banner ${result.passed ? 'pass' : 'fail'}` },
    el('div', { class: 'verdict', text: result.passed ? 'PASS' : 'DID NOT PASS' }),
    el('div', { class: 'scorebig' }, String(result.scaled), el('span', { class: 'of', text: `/${scaleMax}` })),
    el('div', {
      class: 'detail',
      text: `${result.correct} of ${result.total}${scoredOnly} questions correct · ${result.percent}% · passing score is ${passMark}`,
    }),
  );
}

function breakdown(result, config, actions) {
  const rows = Object.entries(result.byDomain).flatMap(([domain, { c, t }]) => {
    const pct = Math.round((c / t) * 100);
    const bar = el('div', { class: 'dbar' }, el('span', { text: `${pct}%` }));
    bar.firstChild.style.width = `${Math.max(pct, 8)}%`;
    return [el('div', { class: 'dlabel' }, domain, ' ', el('small', { class: 'k', text: `(${c}/${t})` })), bar];
  });
  const hasUnscored = config.selection.strategy === 'planned';
  const title = el('h2', { text: `Score by ${config.selection.bucketLabel} ` });
  if (hasUnscored) title.append(el('small', { class: 'k', text: '(scored questions only)' }));
  return el('div', { class: 'card' }, title, ...rows, actions);
}

function reviewItem(question, verdict, index) {
  const heading = el(
    'div',
    { class: 'rev-q' },
    `${index + 1}. ${question.question}`,
    el('span', { class: `badge ${verdict.ok ? 'ok' : 'no'}`, text: verdict.ok ? 'Correct' : 'Incorrect' }),
  );
  if (!question.scored) heading.append(el('span', { class: 'badge uns', text: 'Unscored (pretest)' }));

  const options = question.options.map((option) => {
    const chosen = verdict.chosen.includes(option.text);
    const state = option.correct ? ' correct' : chosen ? ' wrong' : '';
    const mark = option.correct ? '✔ ' : chosen ? '✘ ' : '';
    return el('div', { class: `opt${state}` }, el('span', { text: mark + option.text }));
  });

  return el(
    'div',
    { class: `rev${question.scored ? '' : ' unscored'}` },
    el('div', { class: 'tag', text: question.domain }),
    heading,
    ...options,
    el('div', { class: 'expl' }, el('strong', { text: 'Why: ' }), question.explanation),
  );
}

/**
 * @param {object} view  `{paper, result, config, onRetake, onBack}`
 */
export function renderResults({ paper, result, config, onRetake, onBack }) {
  const actions = el(
    'div',
    { class: 'nav noprint' },
    el('button', { type: 'button', class: 'primary', text: 'Retake (new questions)', onclick: onRetake }),
    el('button', { type: 'button', class: 'ghost', text: 'Back to start', onclick: onBack }),
    el('button', { type: 'button', class: 'ghost', text: 'Print results', onclick: () => window.print() }),
  );

  const children = [
    banner(result, config),
    el('div', { class: 'save-note', id: SAVE_NOTE_ID, text: 'Saving result…' }),
  ];
  if (config.selection.strategy === 'planned') {
    const unscored = paper.filter((q) => !q.scored).length;
    children.push(
      el('div', {
        class: 'note',
        text: `Only the ${result.total} scored questions count toward your mark — the ${unscored} unscored pretest questions are shown below for practice but did not affect your score.`,
      }),
    );
  }
  children.push(
    breakdown(result, config, actions),
    el(
      'div',
      { class: 'card' },
      el('h2', { text: 'Review & explanations' }),
      ...paper.map((question, index) => reviewItem(question, result.verdicts[index], index)),
    ),
  );
  $('results').replaceChildren(...children);
  window.scrollTo(0, 0);
}
