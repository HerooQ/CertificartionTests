/** Mutable state for one exam attempt. Contains no DOM access. */

export class ExamState {
  constructor(paper) {
    this.paper = paper;
    this.answers = {}; // question index -> chosen option texts
    this.flags = {}; // question index -> bool
    this.current = 0;
  }

  isAnswered(index) {
    return (this.answers[index]?.length ?? 0) > 0;
  }

  answeredCount() {
    return this.paper.reduce((n, _, index) => n + (this.isAnswered(index) ? 1 : 0), 0);
  }

  choose(optionText) {
    const question = this.paper[this.current];
    const chosen = this.answers[this.current] ?? [];
    this.answers[this.current] = question.multi
      ? chosen.includes(optionText)
        ? chosen.filter((value) => value !== optionText)
        : [...chosen, optionText]
      : [optionText];
  }

  toggleFlag() {
    this.flags[this.current] = !this.flags[this.current];
  }

  goTo(index) {
    if (index >= 0 && index < this.paper.length) this.current = index;
  }

  get isLast() {
    return this.current === this.paper.length - 1;
  }
}
