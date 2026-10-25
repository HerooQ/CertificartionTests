/**
 * Paper assembly: turns a question bank plus a selection rule into the ordered
 * list of questions a candidate sees. Pure functions; the random source is
 * injectable so behaviour can be tested deterministically.
 */

/** Fisher-Yates shuffle returning a new array. */
export function shuffle(items, rng = Math.random) {
  const copy = items.slice();
  for (let i = copy.length - 1; i > 0; i--) {
    const j = Math.floor(rng() * (i + 1));
    [copy[i], copy[j]] = [copy[j], copy[i]];
  }
  return copy;
}

function groupByBucket(bank) {
  const groups = new Map();
  for (const question of bank) {
    if (!groups.has(question.bucket)) groups.set(question.bucket, []);
    groups.get(question.bucket).push(question);
  }
  return groups;
}

const naturalOrder = (a, b) => a.localeCompare(b, undefined, { numeric: true });

/** Round-robin across buckets so every module is represented evenly. */
function selectBalanced(bank, count, rng) {
  const groups = groupByBucket(bank);
  const buckets = [...groups.keys()].sort(naturalOrder);
  for (const bucket of buckets) groups.set(bucket, shuffle(groups.get(bucket), rng));

  const chosen = [];
  for (let depth = 0; chosen.length < count; depth++) {
    let addedThisRound = false;
    for (const bucket of shuffle(buckets, rng)) {
      const question = groups.get(bucket)[depth];
      if (!question) continue;
      chosen.push({ source: question, scored: true });
      addedThisRound = true;
      if (chosen.length >= count) break;
    }
    if (!addedThisRound) break; // bank exhausted
  }
  return chosen;
}

/** Take an explicit scored + unscored count from each bucket. */
function selectPlanned(bank, plan, rng) {
  const groups = groupByBucket(bank);
  const chosen = [];
  for (const [bucket, { scored, unscored }] of Object.entries(plan)) {
    const pool = shuffle(groups.get(bucket) ?? [], rng).slice(0, scored + unscored);
    pool.forEach((source, index) => chosen.push({ source, scored: index < scored }));
  }
  return chosen;
}

/** Shuffle options while remembering which ones are correct by value. */
function presentQuestion({ source, scored }, rng) {
  const options = shuffle(
    source.options.map((text, index) => ({ text, correct: source.answer.includes(index) })),
    rng,
  );
  return {
    id: source.id,
    bucket: source.bucket,
    domain: source.domain,
    question: source.question,
    explanation: source.explanation,
    multi: source.answer.length > 1,
    options,
    correctValues: options.filter((o) => o.correct).map((o) => o.text),
    scored,
  };
}

/**
 * Build a randomised paper.
 * @param {object[]} bank       question bank (see data/questions/*.json)
 * @param {object}   selection  `{strategy, scored, plan}` from the catalog
 * @param {() => number} rng    random source returning [0, 1)
 */
export function buildPaper(bank, selection, rng = Math.random) {
  const picked =
    selection.strategy === 'planned'
      ? selectPlanned(bank, selection.plan, rng)
      : selectBalanced(bank, selection.scored, rng);
  return shuffle(picked, rng).map((item) => presentQuestion(item, rng));
}
