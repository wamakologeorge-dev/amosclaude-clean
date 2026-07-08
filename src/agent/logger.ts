const levels = {
  debug: 0,
  info: 1,
  warn: 2,
  error: 3,
} as const

export class AgentLogger {
  name: string
  level: keyof typeof levels

  constructor(name: string, level: keyof typeof levels = "info") {
    this.name = name
    this.level = level
  }

  log(level: keyof typeof levels, message: string, meta: Record<string, unknown> = {}) {
    if (levels[level] < levels[this.level]) {
      return
    }

    const timestamp = new Date().toISOString()
    console.log(JSON.stringify({ timestamp, level, service: this.name, message, meta }))
  }

  debug(message: string, meta: Record<string, unknown> = {}) {
    this.log("debug", message, meta)
  }

  info(message: string, meta: Record<string, unknown> = {}) {
    this.log("info", message, meta)
  }

  warn(message: string, meta: Record<string, unknown> = {}) {
    this.log("warn", message, meta)
  }

  error(message: string, meta: Record<string, unknown> = {}) {
    this.log("error", message, meta)
  }
}

export function createLogger(name: string, level: keyof typeof levels = "info") {
  return new AgentLogger(name, level)
}
