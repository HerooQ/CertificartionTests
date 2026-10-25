import assert from 'node:assert/strict';
import { test } from 'node:test';

import { isCorrect, scorePaper } from '../../certprep/static/js/exam/scoring.js';

const policy = { scaleMax: 1000, passMark: 700 };
const q = (domain, correctValues, scored = true) => ({ domain, correctValues, scored });

test('single and multiple-response marking requires an exact match', () => {
  assert.equal(isCorrect(q('d', ['a']), ['a']), true);
  assert.equal(isCorrect(q('d', ['a', 'b']), ['b', 'a']), true);
  assert.equal(isCorrect(q('d', ['a', 'b']), ['a']), false);
  assert.equal(isCorrect(q('d', ['a']), []), false);
});

test('scales the score and applies the pass mark', () => {
  const paper = Array.from({ length: 10 }, () => q('d', ['x']));
  const answers = paper.map((_, i) => (i < 7 ? ['x'] : ['wrong']));
  const result = scorePaper(paper, answers, policy);
  assert.deepEqual([result.correct, result.total, result.scaled, result.percent], [7, 10, 700, 70]);
  assert.equal(result.passed, true);
  assert.equal(scorePaper(paper, paper.map(() => []), policy).passed, false);
});

test('unscored questions are marked but excluded from the result', () => {
  const paper = [q('A', ['x']), q('A', ['x'], false)];
  const result = scorePaper(paper, [['x'], ['x']], policy);
  assert.equal(result.total, 1);
  assert.deepEqual(result.byDomain, { A: { c: 1, t: 1 } });
  assert.equal(result.verdicts[1].ok, true);
});

test('per-domain breakdown tallies each domain separately', () => {
  const paper = [q('A', ['x']), q('A', ['x']), q('B', ['x'])];
  const result = scorePaper(paper, [['x'], ['no'], ['x']], policy);
  assert.deepEqual(result.byDomain, { A: { c: 1, t: 2 }, B: { c: 1, t: 1 } });
});
