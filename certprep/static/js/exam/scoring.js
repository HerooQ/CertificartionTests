/** Marking logic. Pure functions so they can be unit-tested without a DOM. */

/** A multiple-response item is correct only when the selection matches exactly. */
export function isCorrect(question, chosen) {
  const given = [...chosen].sort();
  const expected = [...question.correctValues].sort();
  return given.length === expected.length && given.every((value, i) => value === expected[i]);
}

/**
 * Mark a paper. Only scored questions count towards the result; unscored
 * (pretest) items are still marked so they can be shown in the review.
 *
 * @param {object[]} paper    questions from `buildPaper`
 * @param {Array<string[]>} answers   chosen option texts, indexed like `paper`
 * @param {{scaleMax: number, passMark: number}} policy
 */
export function scorePaper(paper, answers, policy) {
  let correct = 0;
  let scoredTotal = 0;
  const byDomain = {};
  const verdicts = paper.map((question, index) => {
    const chosen = answers[index] ?? [];
    const ok = isCorrect(question, chosen);
    if (question.scored) {
      scoredTotal++;
      const bucket = (byDomain[question.domain] ??= { c: 0, t: 0 });
      bucket.t++;
      if (ok) {
        correct++;
        bucket.c++;
      }
    }
    return { ok, chosen };
  });

  const scaled = Math.round((correct / scoredTotal) * policy.scaleMax);
  return {
    correct,
    total: scoredTotal,
    scaled,
    percent: Math.round((correct / scoredTotal) * 100),
    passed: scaled >= policy.passMark,
    byDomain,
    verdicts,
  };
}
