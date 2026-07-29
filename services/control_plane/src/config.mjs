import { z } from 'zod';

import { parseAllowedCommands } from './policy.mjs';

function integer(name, fallback, minimum, maximum) {
  const raw = process.env[name] ?? String(fallback);
  const parsed = Number.parseInt(raw, 10);
  if (!Number.isInteger(parsed) || parsed < minimum || parsed > maximum) {
    throw new Error(`${name} must be an integer between ${minimum} and ${maximum}.`);
  }
  return parsed;
}

function boolean(name, fallback = false) {
  const raw = String(process.env[name] ?? fallback).trim().toLowerCase();
  if (['1', 'true', 'yes', 'on'].includes(raw)) return true;
  if (['0', 'false', 'no', 'off'].includes(raw)) return false;
  throw new Error(`${name} must be true or false.`);
}

const executionModeSchema = z.enum(['disabled', 'local']);

export const config = Object.freeze({
  host: process.env.AMOSCLAUD_CONTROL_PLANE_HOST?.trim() || '0.0.0.0',
  port: integer('AMOSCLAUD_CONTROL_PLANE_PORT', 8300, 1, 65535),
  token: process.env.AMOSCLAUD_CONTROL_PLANE_TOKEN?.trim() || '',
  redisUrl: process.env.AMOSCLAUD_REDIS_URL?.trim() || 'redis://127.0.0.1:6379/0',
  queueName: process.env.AMOSCLAUD_TASK_QUEUE?.trim() || 'amosclaud-agent-tasks',
  workerConcurrency: integer('AMOSCLAUD_WORKER_CONCURRENCY', 4, 1, 32),
  executionMode: executionModeSchema.parse(
    process.env.AMOSCLAUD_EXECUTION_MODE?.trim() || 'disabled',
  ),
  repositoryStorageRoot:
    process.env.AMOSCLAUD_REPOSITORY_STORAGE_ROOT?.trim() ||
    '/var/lib/amosclaud/repositories',
  allowedCommands: parseAllowedCommands(process.env.AMOSCLAUD_ALLOWED_COMMANDS),
  maxCommandTimeoutMs: integer(
    'AMOSCLAUD_MAX_COMMAND_TIMEOUT_MS',
    900_000,
    1_000,
    3_600_000,
  ),
  runtimeUrl: process.env.AMOSCLAUD_WORKSPACE_RUNTIME_URL?.trim().replace(/\/$/, '') || '',
  runtimeToken: process.env.AMOSCLAUD_WORKSPACE_RUNTIME_TOKEN?.trim() || '',
  watchersEnabled: boolean('AMOSCLAUD_WATCHERS_ENABLED', false),
  watcherReconcileMs: integer('AMOSCLAUD_WATCHER_RECONCILE_MS', 10_000, 2_000, 60_000),
  skillPackages: (process.env.AMOSCLAUD_SKILL_PACKAGES ?? '')
    .split(',')
    .map((item) => item.trim())
    .filter(Boolean),
  skillOutputRoot:
    process.env.AMOSCLAUD_SKILL_OUTPUT_ROOT?.trim() || '/var/lib/amosclaud/skills',
  logRetentionSeconds: integer(
    'AMOSCLAUD_TASK_LOG_RETENTION_SECONDS',
    604_800,
    3_600,
    2_592_000,
  ),
  logMaxEntries: integer('AMOSCLAUD_TASK_LOG_MAX_ENTRIES', 2_000, 100, 20_000),
});

export function readinessProblems() {
  const problems = [];
  if (!config.token) problems.push('AMOSCLAUD_CONTROL_PLANE_TOKEN is not configured');
  if (config.executionMode === 'local' && !config.repositoryStorageRoot) {
    problems.push('AMOSCLAUD_REPOSITORY_STORAGE_ROOT is not configured');
  }
  if (config.watchersEnabled && config.executionMode !== 'local') {
    problems.push('File watchers require AMOSCLAUD_EXECUTION_MODE=local');
  }
  return problems;
}
