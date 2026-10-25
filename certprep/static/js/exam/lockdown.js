/**
 * Exam lockdown: while a paper is in progress, swallow keystrokes and block
 * copy/cut/select/context-menu so questions cannot be trivially copied out.
 * This is a deterrent, not tamper-proof invigilation.
 */

let locked = false;

const blockKey = (event) => {
  if (!locked) return;
  event.preventDefault();
  event.stopPropagation();
};
const blockDefault = (event) => {
  if (locked) event.preventDefault();
};

['keydown', 'keypress', 'keyup'].forEach((type) => document.addEventListener(type, blockKey, true));
['selectstart', 'contextmenu', 'copy', 'cut', 'dragstart'].forEach((type) =>
  document.addEventListener(type, blockDefault, true),
);

export function setExamLock(on) {
  locked = Boolean(on);
  document.body.classList.toggle('exam-locked', locked);
  if (locked) document.activeElement?.blur?.();
}
