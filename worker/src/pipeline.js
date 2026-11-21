// The Durable Object that owns one pipeline container (src/wt_analytics/pipeline/service.py).

import { DurableObject } from "cloudflare:workers";

const PORT = 8080;
const IDLE_MS = 3 * 60 * 1000;
// 2 vCPU: the client and server replays of a battle decode in parallel.
const INSTANCE = "standard-3";

export class Pipeline extends DurableObject {
  async fetch(request) {
    this.starting ??= this.start().finally(() => {
      this.starting = undefined;
    });
    await this.starting;
    const url = new URL(request.url);
    url.protocol = "http:";
    url.host = "container";
    const forwarded = new Request(url, request);
    forwarded.headers.delete("host");
    return this.ctx.container.getTcpPort(PORT).fetch(forwarded);
  }

  async start() {
    const container = this.ctx.container;
    if (!container.running) {
      container.start({ image: container.images.base, instance: INSTANCE, enableInternet: false });
    }
    await container.setInactivityTimeout(IDLE_MS);
    const port = container.getTcpPort(PORT);
    for (let attempt = 0; attempt < 150; attempt++) {
      try {
        const response = await port.fetch("http://container/health", { signal: AbortSignal.timeout(1000) });
        await response.body?.cancel();
        if (response.ok) return;
      } catch {
        // not listening yet
      }
      await scheduler.wait(200);
    }
    throw new Error("pipeline container did not become ready");
  }
}
