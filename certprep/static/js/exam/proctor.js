/**
 * Lightweight proctoring: a mandatory webcam preview plus detection of
 * full-screen exits, tab switches and window blurs. The camera feed stays in
 * the browser; only a short text summary of violations is submitted.
 */

import { $ } from './dom.js';

const TOAST_MS = 4000;
const BLUR_GRACE_MS = 600; // a tab switch also blurs the window; count it once

export const VIOLATION = Object.freeze({
  FULLSCREEN: 'Exited full-screen',
  TAB: 'Switched tab or minimised the window',
  WINDOW: 'Left the exam window (another app or window)',
});

export class Proctor {
  #stream = null;
  #tracking = false;
  #violations = new Map();
  #lastHidden = 0;
  #toastTimer = null;

  constructor() {
    this.box = $('proctor-cam');
    this.video = $('proctor-video');
    this.nameLabel = $('proctor-name');
    this.toast = $('proctor-toast');
  }

  // -- camera ------------------------------------------------------------
  get cameraReady() {
    return Boolean(this.#stream?.getTracks().some((track) => track.readyState === 'live'));
  }

  /** Resolve true once a live camera is available, false if denied/unsupported. */
  async requestCamera() {
    if (this.cameraReady) return true;
    if (!navigator.mediaDevices?.getUserMedia) return false;
    try {
      this.#stream = await navigator.mediaDevices.getUserMedia({
        video: { width: 320, height: 240 },
        audio: false,
      });
      this.video.srcObject = this.#stream;
      return true;
    } catch {
      return false;
    }
  }

  stopCamera() {
    this.#stream?.getTracks().forEach((track) => track.stop());
    this.#stream = null;
  }

  showPreview(candidateName) {
    if (candidateName) this.nameLabel.textContent = candidateName;
    this.box.classList.add('show');
  }

  hidePreview() {
    this.box.classList.remove('show');
  }

  // -- violation tracking ------------------------------------------------
  startTracking() {
    this.#violations = new Map();
    this.#lastHidden = 0;
    this.#tracking = true;
    document.addEventListener('visibilitychange', this.#onVisibility);
    window.addEventListener('blur', this.#onBlur);
    document.addEventListener('fullscreenchange', this.#onFullscreen);
    document.addEventListener('webkitfullscreenchange', this.#onFullscreen);
  }

  stopTracking() {
    this.#tracking = false;
    document.removeEventListener('visibilitychange', this.#onVisibility);
    window.removeEventListener('blur', this.#onBlur);
    document.removeEventListener('fullscreenchange', this.#onFullscreen);
    document.removeEventListener('webkitfullscreenchange', this.#onFullscreen);
  }

  /** Text stored with the result: empty when the attempt was clean. */
  summary() {
    if (!this.#violations.size) return '';
    const parts = [...this.#violations].map(([kind, n]) => (n > 1 ? `${kind} (${n}×)` : kind));
    return `CHEATING FLAGGED — ${parts.join('; ')}`;
  }

  #flag(kind) {
    if (!this.#tracking) return;
    this.#violations.set(kind, (this.#violations.get(kind) ?? 0) + 1);
    this.toast.textContent = `⚠ ${kind} — this has been flagged.`;
    this.toast.classList.add('show');
    clearTimeout(this.#toastTimer);
    this.#toastTimer = setTimeout(() => this.toast.classList.remove('show'), TOAST_MS);
  }

  #onVisibility = () => {
    if (document.visibilityState !== 'hidden') return;
    this.#lastHidden = Date.now();
    this.#flag(VIOLATION.TAB);
  };

  #onBlur = () => {
    if (Date.now() - this.#lastHidden < BLUR_GRACE_MS) return;
    this.#flag(VIOLATION.WINDOW);
  };

  #onFullscreen = () => {
    if (!document.fullscreenElement && !document.webkitFullscreenElement) {
      this.#flag(VIOLATION.FULLSCREEN);
    }
  };
}
