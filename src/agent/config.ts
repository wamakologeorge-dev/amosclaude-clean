const allowedLogLevels = ["debug", "info", "warn", "error"]
const rawLogLevel = process.env.LOG_LEVEL ?? "info"
const normalizedLogLevel = allowedLogLevels.includes(rawLogLevel) ? rawLogLevel : "info"
const rawPort = Number(process.env.PORT ?? 3000)
const normalizedPort = Number.isInteger(rawPort) ? rawPort : 3000

export const config = {
  githubToken: process.env.GITHUB_TOKEN ?? "",
  githubRepository: process.env.GITHUB_REPOSITORY ?? "owner/repo",
  agentName: process.env.AGENT_NAME ?? "amos-claude-agent",
  webhookSecret: process.env.WEBHOOK_SECRET ?? "",
  logLevel: normalizedLogLevel,
  port: normalizedPort,
}
