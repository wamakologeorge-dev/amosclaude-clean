type LoggerLike = {
  info: (message: string, meta?: Record<string, unknown>) => void
}

export class AgentBrain {
  logger: LoggerLike
  context: string[]

  constructor(logger: LoggerLike) {
    this.logger = logger
    this.context = []
  }

  async think(task: string) {
    this.logger.info("Planning agent response", { task })
    this.context.push(task)

    return {
      task,
      summary: `Prepared a response for ${task}`,
      contextSize: this.context.length,
    }
  }
}
