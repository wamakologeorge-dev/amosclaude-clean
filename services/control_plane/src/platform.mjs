import { randomUUID, timingSafeEqual } from 'node:crypto';

import { Queue } from 'bullmq';
import { execa } from 'execa';
import Redis from 'ioredis';

import { config } from './config.mjs';
import {
  assertAllowedCommand,
  publicTaskData,
  resolveRepositoryPath,
  sanitizeEnvironment,
  splitLogLines,
} from './policy.mjs';

export { publicTaskData };

const TASK_PREFIX = 'amosclaud:task';
const WATCHERS_KEY = 'amosclaud:watchers';
const WATCHER_CHANGE_CHANNEL = 'amosclaud:watchers:changed';

export function createRedis() {
  return new Redis(config.redisUrl, {
    maxRetriesPerRequest: null,
    enableReadyCheck: true,
    lazyConnect: false,
  });
}

export function createTaskQueue(connection = createRedis()) {
  return new Queue(config.queueName, {
    connection,
    defaultJobOptions: {
      attempts: 1,
      removeOnComplete: { age: config.logRetentionSeconds, count: 5_000 },
      removeOnFail: { age: config.logRetentionSeconds, count: 5_000 },
    },
  });
}

function taskKey(taskId, suffix) {
  return `${TASK_PREFIX}:${taskId}:${suffix}`;
}

export async function appendTaskLog(redis, taskId, stream, message) {
  const clean = String(message ?? '').replaceAll('\0', '').slice(0, 16_000);
  if (!clean) return null;
  const sequenceKey = taskKey(taskId, 'log-sequence');
  const logsKey = taskKey(taskId, 'logs');
  const channel = taskKey(taskId, 'events');
  const sequence = await redis.incr(sequenceKey);
  const entry = JSON.stringify({
    sequence,
    timestamp: new Date().toISOString(),
    stream,
    message: clean,
  });
  await redis
    .multi()
    .rpush(logsKey, entry)
    .ltrim(logsKey, -config.logMaxEntries, -1)
    .expire(logsKey, config.logRetentionSeconds)
    .expire(sequenceKey, config.logRetentionSeconds)
    .publish(channel, entry)
    .exec();
  return JSON.parse(entry);
}

export async function appendChunk(redis, taskId, stream, chunk) {
  for (const line of splitLogLines(chunk)) {
    await appendTaskLog(redis, taskId, stream, line);
  }
}

export async function getTaskLogs(redis, taskId, after = 0) {
  const rows = await redis.lrange(taskKey(taskId, 'logs'), 0, -1);
  return rows
    .map((row) => {
      try {
        return JSON.parse(row);
      } catch {
        return null;
      }
    })
    .filter((entry) => entry && entry.sequence > after);
}

export function taskEventChannel(taskId) {
  return taskKey(taskId, 'events');
}

export async function requestCancellation(redis, taskId) {
  await redis.set(taskKey(taskId, 'cancel'), '1', 'EX', config.logRetentionSeconds);
  await appendTaskLog(redis, taskId, 'system', 'Cancellation requested.');
}

export async function cancellationRequested(redis, taskId) {
  return (await redis.exists(taskKey(taskId, 'cancel'))) === 1;
}

export function authenticateToken(suppliedToken) {
  if (!config.token) return false;
  const supplied = Buffer.from(String(suppliedToken ?? ''));
  const expected = Buffer.from(config.token);
  return supplied.length === expected.length && timingSafeEqual(supplied, expected);
}

export function bearerToken(header) {
  const value = String(header ?? '');
  return value.startsWith('Bearer ') ? value.slice(7).trim() : '';
}

export async function enqueueTask(queue, data, options = {}) {
  const job = await queue.add(data.type, data, {
    jobId: options.jobId,
    priority: options.priority,
  });
  return { id: job.id, name: job.name, data: publicTaskData(job.data) };
}

function runtimeConfigured() {
  return Boolean(config.runtimeUrl && config.runtimeToken);
}

async function runtimeRequest(method, pathname, body) {
  if (!runtimeConfigured()) {
    throw new Error('The isolated workspace runtime is not configured.');
  }
  const response = await fetch(`${config.runtimeUrl}${pathname}`, {
    method,
    headers: {
      Authorization: `Bearer ${config.runtimeToken}`,
      ...(body ? { 'Content-Type': 'application/json' } : {}),
    },
    body: body ? JSON.stringify(body) : undefined,
    signal: AbortSignal.timeout(30_000),
  });
  if (!response.ok) {
    let detail = `${response.status} ${response.statusText}`;
    try {
      const payload = await response.json();
      detail = payload.detail || detail;
    } catch {
      // Keep the status text when the runtime did not return JSON.
    }
    throw new Error(`Workspace runtime request failed: ${detail}`);
  }
  if (response.status === 204) return {};
  return response.json();
}

export const runtimeClient = Object.freeze({
  configured: runtimeConfigured,
  health: () => runtimeRequest('GET', '/health'),
  start: (task) =>
    runtimeRequest('POST', '/v1/workspaces', {
      workspace_id: task.workspaceId,
      repository_id: task.repositoryId,
      owner_id: task.ownerId,
      environment: sanitizeEnvironment(task.environment, {}),
    }),
  stop: (workspaceId) =>
    runtimeRequest('POST', `/v1/workspaces/${encodeURIComponent(workspaceId)}/stop`),
  status: (workspaceId) =>
    runtimeRequest('GET', `/v1/workspaces/${encodeURIComponent(workspaceId)}`),
});

function createLineSink(redis, taskId, stream) {
  let remainder = '';
  let chain = Promise.resolve();
  const write = (chunk) => {
    const normalized = `${remainder}${String(chunk)}`
      .replace(/\r\n/g, '\n')
      .replace(/\r/g, '\n');
    const lines = normalized.split('\n');
    remainder = lines.pop() ?? '';
    for (const line of lines) {
      if (!line) continue;
      chain = chain.then(() => appendTaskLog(redis, taskId, stream, line));
    }
  };
  const flush = async () => {
    if (remainder) {
      chain = chain.then(() => appendTaskLog(redis, taskId, stream, remainder));
      remainder = '';
    }
    await chain;
  };
  return { write, flush };
}

export async function executeLocalCommand(redis, taskId, task) {
  if (config.executionMode !== 'local') {
    throw new Error('Local command execution is disabled by policy.');
  }
  const command = assertAllowedCommand(task.command, config.allowedCommands);
  const timeout = Math.min(task.timeoutMs, config.maxCommandTimeoutMs);
  const { cwd } = await resolveRepositoryPath(
    config.repositoryStorageRoot,
    task.repositoryId,
    task.cwd,
  );
  const environment = sanitizeEnvironment(task.environment);
  await appendTaskLog(redis, taskId, 'system', `Starting ${command} in ${cwd}`);

  const child = execa(command, task.args, {
    cwd,
    env: environment,
    extendEnv: false,
    shell: false,
    reject: false,
    timeout,
    stdout: 'pipe',
    stderr: 'pipe',
    buffer: false,
    windowsHide: true,
  });
  const stdout = createLineSink(redis, taskId, 'stdout');
  const stderr = createLineSink(redis, taskId, 'stderr');
  child.stdout?.on('data', stdout.write);
  child.stderr?.on('data', stderr.write);

  let cancellationObserved = false;
  const cancellationTimer = setInterval(async () => {
    try {
      if (!cancellationObserved && (await cancellationRequested(redis, taskId))) {
        cancellationObserved = true;
        child.kill('SIGTERM');
      }
    } catch {
      // Redis errors are reported through the worker's normal failure path.
    }
  }, 500);
  cancellationTimer.unref();

  try {
    const result = await child;
    await Promise.all([stdout.flush(), stderr.flush()]);
    const exitCode = Number.isInteger(result.exitCode) ? result.exitCode : 1;
    const succeeded = exitCode === 0 && !result.timedOut && !cancellationObserved;
    await appendTaskLog(
      redis,
      taskId,
      'system',
      succeeded
        ? `Command completed with exit code ${exitCode}.`
        : `Command stopped with exit code ${exitCode}.`,
    );
    return {
      succeeded,
      exitCode,
      timedOut: Boolean(result.timedOut),
      canceled: cancellationObserved,
      command,
      cwd,
    };
  } finally {
    clearInterval(cancellationTimer);
  }
}

export async function listWatchers(redis) {
  const values = await redis.hvals(WATCHERS_KEY);
  return values
    .map((value) => {
      try {
        return JSON.parse(value);
      } catch {
        return null;
      }
    })
    .filter(Boolean)
    .sort((a, b) => a.createdAt.localeCompare(b.createdAt));
}

export async function createWatcher(redis, input) {
  const watcher = {
    id: `watch_${randomUUID().replaceAll('-', '')}`,
    ...input,
    createdAt: new Date().toISOString(),
  };
  await redis
    .multi()
    .hset(WATCHERS_KEY, watcher.id, JSON.stringify(watcher))
    .publish(WATCHER_CHANGE_CHANNEL, watcher.id)
    .exec();
  return watcher;
}

export async function deleteWatcher(redis, watcherId) {
  const deleted = await redis.hdel(WATCHERS_KEY, watcherId);
  await redis.publish(WATCHER_CHANGE_CHANNEL, watcherId);
  return deleted === 1;
}

export const watcherKeys = Object.freeze({
  registry: WATCHERS_KEY,
  changes: WATCHER_CHANGE_CHANNEL,
  leader: 'amosclaud:watchers:leader',
});
