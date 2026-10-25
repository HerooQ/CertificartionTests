/**
 * Exam page controller: intro -> camera check -> rules -> timed paper -> results.
 */

import { fetchQuestions, submitResult } from './api.js';
import { Celebration } from './celebrate.js';
import { ExamClock } from './clock.js';
import { $, hide, show } from './dom.js';
import { setExamLock } from './lockdown.js';
import { buildPaper } from './paper.js';
import { Proctor } from './proctor.js';
import { renderResults, setSaveNote } from './results.js';
import { scorePaper } from './scoring.js';
import { ExamState } from './state.js';
import { buildNavigator, confirmDialog, renderQuestion, renderTimer } from './view.js';

const config = JSON.parse($('exam-config').textContent);
const proctor = new Proctor();
const celebration = new Celebration($('celebrate-canvas'));

let student = { first: '', surname: '' };
let state = null;
let clock = null;
let submitted = false;
let bank = null;

const candidateName = () => `${student.first} ${student.surname}`.trim();

// -- intro -> rules ------------------------------------------------------
async function onNameSubmit(event) {
  event.preventDefault();
  const first = $('fname').value.trim();
  const surname = $('sname').value.trim();
  if (!first || !surname) {
    alert('Please enter your first name and surname before starting the exam.');
    return;
  }
  student = { first, surname };

  if (!(await proctor.requestCamera())) {
    alert(
      'This is a proctored exam and requires camera access.\n\n' +
        'Please allow the camera when prompted (or enable it in your browser’s site settings) ' +
        'and click Start exam again.\n\n' +
        'If you opened this over a plain http:// address, use the https:// (ngrok) link instead — ' +
        'browsers only allow the camera on secure links.',
    );
    return;
  }
  proctor.showPreview(candidateName());
  showRules();
}

function showRules() {
  $('rules-ack').checked = false;
  $('rules-begin').disabled = true;
  hide($('intro'));
  show($('rules'));
  window.scrollTo(0, 0);
}

function backToIntro() {
  hide($('rules'));
  hide($('results'));
  proctor.stopCamera();
  proctor.hidePreview();
  show($('intro'));
  window.scrollTo(0, 0);
}

// -- exam ----------------------------------------------------------------
async function startExam() {
  if (!(await proctor.requestCamera())) {
    alert('Camera access is required to start the exam. Please allow the camera and try again.');
    return;
  }
  try {
    bank ??= await fetchQuestions(config.questionsUrl);
  } catch (error) {
    alert(`Could not load the questions: ${error.message}`);
    return;
  }

  setExamLock(true);
  document.documentElement.requestFullscreen?.().catch(() => {
    /* if full-screen is refused, later exits are still flagged */
  });
  proctor.startTracking();

  submitted = false;
  state = new ExamState(buildPaper(bank, config.selection));
  hide($('rules'));
  hide($('results'));
  show($('exam'));
  proctor.showPreview(candidateName());
  buildNavigator(state.paper.length, (index) => {
    state.goTo(index);
    paint();
  });
  paint();

  clock?.stop();
  clock = new ExamClock({
    durationSeconds: config.durationSeconds,
    test: config.name,
    student: () => student,
    onTick: renderTimer,
    onExpire: submit,
  });
  clock.start();
}

const paint = () => renderQuestion(state, onChoose);

function onChoose(optionText) {
  state.choose(optionText);
  paint();
}

async function onSubmitClick() {
  const unanswered = state.paper.length - state.answeredCount();
  const message =
    unanswered > 0
      ? `You have ${unanswered} unanswered question(s). Submit anyway?`
      : 'Submit your exam for scoring?';
  if (await confirmDialog(message)) submit();
}

async function submit() {
  if (submitted) return;
  submitted = true;
  setExamLock(false);
  clock.stop();
  proctor.stopTracking(); // submitting may leave full-screen; don't flag that

  const result = scorePaper(state.paper, state.answers, config);
  hide($('exam'));
  show($('results'));
  renderResults({ paper: state.paper, result, config, onRetake: retake, onBack: backToIntro });
  proctor.hidePreview();
  proctor.stopCamera();
  if (result.passed) celebration.play(4500);

  try {
    await submitResult(config.name, student, result, proctor.summary());
    setSaveNote('Result saved to the database ✓');
  } catch {
    setSaveNote('Result not saved — open this test through the exam server to record marks.');
  }
}

function retake() {
  startExam();
}

// -- wiring ----------------------------------------------------------------
$('name-form').addEventListener('submit', onNameSubmit);
$('rules-ack').addEventListener('change', (e) => ($('rules-begin').disabled = !e.target.checked));
$('rules-begin').addEventListener('click', startExam);
$('rules-back').addEventListener('click', backToIntro);
$('prev-btn').addEventListener('click', () => {
  state.goTo(state.current - 1);
  paint();
});
$('next-btn').addEventListener('click', () => {
  if (state.isLast) {
    onSubmitClick();
    return;
  }
  state.goTo(state.current + 1);
  paint();
});
$('flag-btn').addEventListener('click', () => {
  state.toggleFlag();
  paint();
});
$('submit-btn').addEventListener('click', onSubmitClick);

// Returning to a backgrounded tab: re-anchor the timer to the server.
document.addEventListener('visibilitychange', () => {
  if (document.visibilityState === 'visible' && !submitted && clock?.running) clock.sync();
});
