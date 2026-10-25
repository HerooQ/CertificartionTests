/**
 * Exam countdown anchored to the server's clock. The server stamps each
 * attempt's deadline once, so reloading or reopening the tab cannot reset it.
 * If the server is unreachable the local countdown simply carries on.
 */

import { syncClock } from './api.js';

const TICK_MS = 1000;
const RESYNC_MS = 15000;

export class ExamClock {
  #endsAt = 0;
  #tickTimer = null;
  #syncTimer = null;

  /**
   * @param {object} options
   * @param {number} options.durationSeconds
   * @param {string} options.test        exam name (the server's lookup key)
   * @param {() => {first: string, surname: string}} options.student
   * @param {(secondsLeft: number) => void} options.onTick
   * @param {() => void} options.onExpire
   */
  constructor({ durationSeconds, test, student, onTick, onExpire }) {
    Object.assign(this, { durationSeconds, test, student, onTick, onExpire });
  }

  get running() {
    return this.#tickTimer !== null;
  }

  start() {
    this.stop();
    this.#endsAt = Date.now() + this.durationSeconds * 1000; // optimistic until synced
    this.#tickTimer = setInterval(() => this.#tick(), TICK_MS);
    this.#syncTimer = setInterval(() => this.sync(), RESYNC_MS);
    this.#tick();
    this.sync();
  }

  stop() {
    clearInterval(this.#tickTimer);
    clearInterval(this.#syncTimer);
    this.#tickTimer = this.#syncTimer = null;
  }

  /** Re-anchor to the server's authoritative remaining time. */
  async sync() {
    try {
      const { ok, remaining } = await syncClock(this.test, this.student());
      if (!ok || typeof remaining !== 'number' || !this.running) return;
      this.#endsAt = Date.now() + remaining * 1000;
      this.#tick();
    } catch {
      /* offline: keep the local countdown */
    }
  }

  #tick() {
    const left = Math.max(0, Math.round((this.#endsAt - Date.now()) / 1000));
    this.onTick(left);
    if (left <= 0 && this.running) {
      this.stop();
      this.onExpire();
    }
  }
}
