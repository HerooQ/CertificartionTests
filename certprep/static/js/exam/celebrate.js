/** Confetti and fireworks shown when a candidate passes. */

const COLORS = ['#FF9900', '#EC7211', '#1a7f37', '#007faa', '#232F3E', '#ffd400', '#ff5a5a'];
const pick = (list) => list[Math.floor(Math.random() * list.length)];

export class Celebration {
  constructor(canvas) {
    this.canvas = canvas;
    this.ctx = canvas.getContext('2d');
    this.particles = [];
    this.running = false;
    this.frame = null;
    window.addEventListener('resize', () => this.#resize());
  }

  #resize() {
    this.canvas.width = window.innerWidth;
    this.canvas.height = window.innerHeight;
  }

  #confetti(x, y, count) {
    for (let i = 0; i < count; i++) {
      const angle = Math.random() * Math.PI * 2;
      const speed = 2 + Math.random() * 6;
      this.particles.push({
        type: 'confetti', x, y,
        vx: Math.cos(angle) * speed, vy: Math.sin(angle) * speed - 3,
        size: 5 + Math.random() * 5, color: pick(COLORS),
        rot: Math.random() * 360, vrot: (Math.random() - 0.5) * 14,
        life: 0, maxLife: 110 + Math.random() * 40,
      });
    }
  }

  #firework(x, y) {
    const count = 45;
    const color = pick(COLORS);
    for (let i = 0; i < count; i++) {
      const angle = (Math.PI * 2 * i) / count;
      const speed = 2 + Math.random() * 3.5;
      this.particles.push({
        type: 'spark', x, y,
        vx: Math.cos(angle) * speed, vy: Math.sin(angle) * speed,
        size: 2 + Math.random() * 2, color, life: 0, maxLife: 55 + Math.random() * 20,
      });
    }
  }

  #step(p) {
    p.life++;
    p.x += p.vx;
    p.y += p.vy;
    if (p.type === 'confetti') {
      p.vy += 0.12;
      p.rot += p.vrot;
    } else {
      p.vx *= 0.96;
      p.vy *= 0.96;
      p.vy += 0.03;
    }
  }

  #draw(p) {
    const { ctx } = this;
    ctx.save();
    ctx.globalAlpha = Math.max(0, 1 - p.life / p.maxLife);
    ctx.translate(p.x, p.y);
    ctx.fillStyle = p.color;
    if (p.type === 'confetti') {
      ctx.rotate((p.rot * Math.PI) / 180);
      ctx.fillRect(-p.size / 2, -p.size / 2, p.size, p.size * 0.6);
    } else {
      ctx.beginPath();
      ctx.arc(0, 0, p.size, 0, Math.PI * 2);
      ctx.fill();
    }
    ctx.restore();
  }

  #tick = () => {
    const { canvas, ctx } = this;
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    this.particles.forEach((p) => {
      this.#step(p);
      this.#draw(p);
    });
    this.particles = this.particles.filter((p) => p.life < p.maxLife && p.y < canvas.height + 40);
    if (this.running || this.particles.length) {
      this.frame = requestAnimationFrame(this.#tick);
    } else {
      this.frame = null;
      canvas.style.display = 'none';
    }
  };

  play(durationMs = 4000) {
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;
    this.#resize();
    this.canvas.style.display = 'block';
    this.running = true;
    const { width, height } = this.canvas;
    const confettiTimer = setInterval(() => {
      this.#confetti(0, -20, 6);
      this.#confetti(width, -20, 6);
      this.#confetti(width / 2, -20, 4);
    }, 180);
    const fireworkTimer = setInterval(
      () => this.#firework(width * (0.15 + Math.random() * 0.7), height * (0.15 + Math.random() * 0.45)),
      420,
    );
    if (!this.frame) this.#tick();
    setTimeout(() => {
      clearInterval(confettiTimer);
      clearInterval(fireworkTimer);
      this.running = false;
    }, durationMs);
  }
}
