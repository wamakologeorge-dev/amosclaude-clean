export class AmosclaudLoggingClient {
  constructor({ endpoint, apiKey, fetchImpl = globalThis.fetch }) {
    this.endpoint = endpoint.replace(/\/$/, ""); this.apiKey = apiKey; this.fetch = fetchImpl;
  }
  event({ message, service, level = "INFO", ...context }) {
    return { event_id: crypto.randomUUID(), timestamp: new Date().toISOString(), level: level.toUpperCase(), message, service, ...context };
  }
  async send(event) { return this.#post("/v1/logs", event); }
  async sendBatch(events) { return this.#post("/v1/logs/batch", { events }); }
  async #post(path, body) {
    const response = await this.fetch(`${this.endpoint}${path}`, { method:"POST", headers:{"content-type":"application/json","X-Amosclaud-Key":this.apiKey}, body:JSON.stringify(body) });
    if (!response.ok) throw new Error(`Amosclaud logging request failed: ${response.status}`);
    return response.json();
  }
}
