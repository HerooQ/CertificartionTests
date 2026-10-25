import assert from 'node:assert/strict';
import { test } from 'node:test';

import { buildPaper, shuffle } from '../../certprep/static/js/exam/paper.js';

/** Deterministic pseudo-random source (mulberry32). */
function seeded(seed) {
  let a = seed;
  return () => {
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

const makeBank = (buckets, perBucket) =>
  buckets.flatMap((bucket) =>
    Array.from({ length: perBucket }, (_, i) => ({
      id: `${bucket}-${i}`,
      bucket,
      domain: `Domain ${bucket}`,
      question: `Question ${bucket}-${i}`,
      options: ['a', 'b', 'c', 'd'],
      answer: i % 2 ? [0, 2] : [1],
      explanation: 'because',
    })),
  );

test('shuffle returns a permutation without mutating the input', () => {
  const input = [1, 2, 3, 4, 5];
  const out = shuffle(input, seeded(1));
  assert.deepEqual([...out].sort(), [1, 2, 3, 4, 5]);
  assert.deepEqual(input, [1, 2, 3, 4, 5]);
});

test('balanced selection draws evenly across buckets', () => {
  const bank = makeBank(['M1', 'M2', 'M3', 'M4'], 20);
  const paper = buildPaper(bank, { strategy: 'balanced', scored: 40 }, seeded(7));
  assert.equal(paper.length, 40);
  assert.ok(paper.every((q) => q.scored));
  const counts = Object.values(Object.groupBy(paper, (q) => q.bucket)).map((g) => g.length);
  assert.deepEqual(counts, [10, 10, 10, 10]);
});

test('balanced selection stops when the bank is exhausted', () => {
  const paper = buildPaper(makeBank(['M1'], 5), { strategy: 'balanced', scored: 50 }, seeded(2));
  assert.equal(paper.length, 5);
});

test('planned selection honours scored and unscored counts per bucket', () => {
  const bank = makeBank(['D1', 'D2'], 12);
  const plan = { D1: { scored: 5, unscored: 2 }, D2: { scored: 3, unscored: 1 } };
  const paper = buildPaper(bank, { strategy: 'planned', plan }, seeded(3));
  assert.equal(paper.length, 11);
  assert.equal(paper.filter((q) => q.scored).length, 8);
  assert.equal(paper.filter((q) => q.bucket === 'D1' && !q.scored).length, 2);
});

test('options are shuffled but correctness travels with the text', () => {
  const [question] = buildPaper(makeBank(['M1'], 1), { strategy: 'balanced', scored: 1 }, seeded(4));
  assert.deepEqual([...question.correctValues], ['b']);
  assert.equal(question.multi, false);
  assert.deepEqual(question.options.map((o) => o.text).sort(), ['a', 'b', 'c', 'd']);
});

test('every real question bank can produce a full paper', async () => {
  const { readFile } = await import('node:fs/promises');
  const catalog = JSON.parse(await readFile('data/catalog.json', 'utf8'));
  for (const exam of catalog.groups.flatMap((g) => g.exams)) {
    const bank = JSON.parse(await readFile(`data/questions/${exam.slug}.json`, 'utf8'));
    const paper = buildPaper(bank, exam.selection);
    const scored = paper.filter((q) => q.scored).length;
    const expected = exam.selection.scored ?? Object.values(exam.selection.plan).reduce((n, b) => n + b.scored, 0);
    assert.equal(scored, expected, exam.slug);
    assert.equal(new Set(paper.map((q) => q.id)).size, paper.length, `${exam.slug} has duplicate questions`);
  }
});
