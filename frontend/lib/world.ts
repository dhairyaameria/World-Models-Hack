// A "world" is whatever produces the first-person video the agent sees.
//  - ReactorWorld: the real Lingbot-World-2 stream (costs money while running).
//  - StaticWorld: free stand-in that pans/zooms the reference image, so the whole
//    agent loop can be developed and tested without a Reactor key.

import { LingbotWorld2Model } from "@reactor-models/lingbot-world-2";
import type { Action } from "./contract";

export interface World {
  start(referenceImageUrl: string, prompt: string): Promise<void>;
  /** Apply an action for action.duration_ms, then go idle. A newer action replaces it. */
  sendAction(action: Action): void;
  setPrompt(prompt: string): Promise<void>;
  /** Current frame as base64 JPEG (no data: prefix), or null if no frame yet. */
  captureFrame(maxWidth?: number, quality?: number): string | null;
  stop(): Promise<void>;
  readonly video: HTMLVideoElement | HTMLCanvasElement;
  onStatus?: (status: string) => void;
}

function frameToJpeg(source: CanvasImageSource, w: number, h: number, maxWidth: number, quality: number) {
  if (!w || !h) return null;
  const scale = Math.min(1, maxWidth / w);
  const c = document.createElement("canvas");
  c.width = Math.round(w * scale);
  c.height = Math.round(h * scale);
  c.getContext("2d")!.drawImage(source, 0, 0, c.width, c.height);
  return c.toDataURL("image/jpeg", quality).split(",")[1] ?? null;
}

async function fetchReactorJwt(): Promise<string> {
  const res = await fetch("/api/reactor-token", { method: "POST" });
  const body = await res.json();
  if (!res.ok) throw new Error(body.error ?? "could not get Reactor token");
  return body.jwt;
}

export class ReactorWorld implements World {
  readonly video: HTMLVideoElement;
  onStatus?: (status: string) => void;
  private model: LingbotWorld2Model | null = null;
  private idleTimer: ReturnType<typeof setTimeout> | null = null;

  /** Degrees per generated frame while looking (Reactor range 0-30). */
  constructor(private rotationSpeedDeg = 3) {
    this.video = document.createElement("video");
    this.video.autoplay = true;
    this.video.muted = true;
    this.video.playsInline = true;
  }

  async start(referenceImageUrl: string, prompt: string) {
    const model = new LingbotWorld2Model();
    this.model = model;
    model.on("statusChanged", (s) => this.onStatus?.(s));
    model.onMainVideo((_track, stream) => {
      this.video.srcObject = stream;
      void this.video.play().catch(() => {});
    });
    model.onCommandError((e) => console.warn("[reactor] command_error", e));

    await model.connect(fetchReactorJwt);
    const blob = await (await fetch(referenceImageUrl)).blob();
    const ref = await model.uploadFile(blob, { name: "reference.jpg" });
    await model.setImage({ image: ref });
    await model.setPrompt({ prompt });
    await model.setRotationSpeedDeg({ rotation_speed_deg: this.rotationSpeedDeg });
    await model.start();
  }

  sendAction(action: Action) {
    const m = this.model;
    if (!m) return;
    if (this.idleTimer) clearTimeout(this.idleTimer);
    void m.setMoveLongitudinal({ move_longitudinal: action.move === "W" ? "forward" : action.move === "S" ? "back" : "idle" });
    void m.setMoveLateral({ move_lateral: action.move === "A" ? "strafe_left" : action.move === "D" ? "strafe_right" : "idle" });
    void m.setLookHorizontal({ look_horizontal: action.look === "left" || action.look === "right" ? action.look : "idle" });
    void m.setLookVertical({ look_vertical: action.look === "up" || action.look === "down" ? action.look : "idle" });
    this.idleTimer = setTimeout(() => this.idle(), action.duration_ms);
  }

  private idle() {
    const m = this.model;
    if (!m) return;
    void m.setMoveLongitudinal({ move_longitudinal: "idle" });
    void m.setMoveLateral({ move_lateral: "idle" });
    void m.setLookHorizontal({ look_horizontal: "idle" });
    void m.setLookVertical({ look_vertical: "idle" });
  }

  async setPrompt(prompt: string) {
    await this.model?.setPrompt({ prompt });
  }

  captureFrame(maxWidth = 640, quality = 0.8) {
    return frameToJpeg(this.video, this.video.videoWidth, this.video.videoHeight, maxWidth, quality);
  }

  async stop() {
    if (this.idleTimer) clearTimeout(this.idleTimer);
    const m = this.model;
    this.model = null;
    if (m) {
      await m.reset().catch(() => {});
      await m.disconnect().catch(() => {});
    }
    this.video.srcObject = null;
  }
}

/** Free offline world: a camera "moving" over the reference image. */
export class StaticWorld implements World {
  readonly video: HTMLCanvasElement;
  onStatus?: (status: string) => void;
  private img: HTMLImageElement | null = null;
  private raf = 0;
  private cam = { yaw: 0, zoom: 1 };
  private vel = { yaw: 0, zoom: 0 };
  private idleAt = 0;
  private caption = "";

  constructor() {
    this.video = document.createElement("canvas");
    this.video.width = 1280;
    this.video.height = 720;
  }

  async start(referenceImageUrl: string, prompt: string) {
    this.onStatus?.("connecting");
    this.caption = prompt;
    this.img = await new Promise<HTMLImageElement | null>((resolve) => {
      const img = new Image();
      img.crossOrigin = "anonymous";
      img.onload = () => resolve(img);
      img.onerror = () => resolve(null); // no reference image yet: draw a placeholder
      img.src = referenceImageUrl;
    });
    this.onStatus?.("ready");
    let last = performance.now();
    const tick = (now: number) => {
      const dt = (now - last) / 1000;
      last = now;
      if (now > this.idleAt) this.vel = { yaw: 0, zoom: 0 };
      this.cam.yaw += this.vel.yaw * dt;
      this.cam.zoom = Math.min(2.5, Math.max(1, this.cam.zoom + this.vel.zoom * dt));
      this.draw();
      this.raf = requestAnimationFrame(tick);
    };
    this.raf = requestAnimationFrame(tick);
  }

  sendAction(action: Action) {
    this.vel = {
      yaw: action.look === "left" ? -0.25 : action.look === "right" ? 0.25 : 0,
      zoom: action.move === "W" ? 0.15 : action.move === "S" ? -0.15 : 0,
    };
    if (action.move === "A") this.vel.yaw = -0.12;
    if (action.move === "D") this.vel.yaw = 0.12;
    this.idleAt = performance.now() + action.duration_ms;
  }

  async setPrompt(prompt: string) {
    this.caption = prompt;
  }

  private draw() {
    const c = this.video;
    const ctx = c.getContext("2d")!;
    const { width: W, height: H } = c;
    if (this.img) {
      const z = this.cam.zoom;
      const sw = this.img.width / z;
      const sh = this.img.height / z;
      const maxShift = (this.img.width - sw) / 2;
      const sx = (this.img.width - sw) / 2 + Math.max(-1, Math.min(1, this.cam.yaw)) * maxShift;
      const sy = (this.img.height - sh) / 2;
      ctx.drawImage(this.img, sx, sy, sw, sh, 0, 0, W, H);
    } else {
      const g = ctx.createLinearGradient(0, 0, 0, H);
      g.addColorStop(0, "#1e293b");
      g.addColorStop(1, "#0f172a");
      ctx.fillStyle = g;
      ctx.fillRect(0, 0, W, H);
      ctx.fillStyle = "#64748b";
      ctx.font = "28px sans-serif";
      ctx.fillText("StaticWorld: no reference image yet", 40, 60);
      ctx.font = "18px sans-serif";
      ctx.fillText(this.caption.slice(0, 120), 40, 100);
      ctx.strokeStyle = "#334155";
      const vx = W / 2 - this.cam.yaw * 300;
      for (let i = -8; i <= 8; i++) {
        ctx.beginPath();
        ctx.moveTo(vx, H / 2);
        ctx.lineTo(W / 2 + i * 200 * this.cam.zoom, H);
        ctx.stroke();
      }
    }
  }

  captureFrame(maxWidth = 640, quality = 0.8) {
    return frameToJpeg(this.video, this.video.width, this.video.height, maxWidth, quality);
  }

  async stop() {
    cancelAnimationFrame(this.raf);
  }
}
