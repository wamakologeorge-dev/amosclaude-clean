import { randomUUID } from 'node:crypto';

import { Worker } from 'bullmq';
import chokidar from 'chokidar';

import { config, readinessProblems } from './config.mjs';
import { taskSchema, watcherInputSchema } from './contracts.mjs';
import {
  appendTaskLog,
  createRedis,
  createTaskQueue,
  enqueueTask,
  executeLocalCommand,
  listWatchers,
  runtimeClient,
  watcherKeys,
} from './platform.mjs';
import { assertAllowedCommand, resolveRepositoryPath } from './policy.mjs';

async function processTask(redis, job) {
  const task = taskSchema.parse(job.data);
  const taskId = String(job.id);
  await appendTaskLog(redis, taskId, 'system', `Task ${task.type} started.`);
  await job.updateProgress({ stage: 'running', startedAt: new Date().toISOString() });

  try {
    let result;
    if (task.type === 'command') {
      result = await executeLocalCommand(redis, taskId, task);
    } else if (task.type === 'runtime.start') {
      result = await runtimeClient.start(task);
    } else if (task.type === 'runtime.stop') {
      result = await runtimeClient.stop(task.workspaceId);
    } else {
      result = await runtimeClient.status(task.workspaceId);
    }
    await job.updateProgress({ stage: 'completed', finishedAt: new Date().toISOString() });
    await appendTaskLog(redis, taskId, 'system', `Task ${task.type} completed.`);
    return result;
  } catch (error) {
    await appendTaskLog(
      redis,
      taskId,
      'system',
      `Task ${task.type} failed: ${error.message}`,
    );
    throw error;
  }
}

class WatcherSupervisor {
  constructor(redis, queue) {
    this.redis = redis;
    this.queue = queue;
    this.token = randomUUID();
    this.active = new Map();
    this.leader = false;
    this.timer = null;
    this.running = false;
  }

  async start() {
    if (!config.watchersEnabled || config.executionMode !== 'local') return;
    this.running = true;
    await this.tick();
    this.timer = setInterval(() => this.tick().catch(console.error), 5_000);
    this.timer.unref();
  }

  async stop() {
    this.running = false;
    if (this.timer) clearInterval(this.timer);
    await this.closeAll();
    await this.releaseLeadership();
  }

  async tick() {
    if (!this.running) return;
    if (!this.leader) {
      const acquired = await this.redis.set(
        watcherKeys.leader,
        this.token,
        'PX',
        15_000,
        'NX',
      );
      this.leader = acquired === 'OK';
      if (!this.leader) return;
    } else {
      const renewed = await this.redis.eval(
        `if redis.call('get', KEYS[1]) == ARGV[1] then
           return redis.call('pexpire', KEYS[1], ARGV[2])
         end
         return 0`,
        1,
        watcherKeys.leader,
        this.token,
        15_000,
      );
      if (Number(renewed) !== 1) {
        this.leader = false;
        await this.closeAll();
        return;
      }
    }
    await this.reconcile();
  }

  async releaseLeadership() {
    if (!this.leader) return;
    await this.redis.eval(
      `if redis.call('get', KEYS[1]) == ARGV[1] then
         return redis.call('del', KEYS[1])
       end
       return 0`,
      1,
      watcherKeys.leader,
      this.token,
    );
    this.leader = false;
  }

  async closeAll() {
    const closing = [];
    for (const record of this.active.values()) {
      clearTimeout(record.debounceTimer);
      closing.push(record.watcher.close());
    }
    this.active.clear();
    await Promise.allSettled(closing);
  }

  async reconcile() {
    const watchers = await listWatchers(this.redis);
    const desired = new Map(watchers.map((watcher) => [watcher.id, watcher]));

    for (const [id, record] of this.active.entries()) {
      const next = desired.get(id);
      if (!next || JSON.stringify(next) !== record.serialized) {
        clearTimeout(record.debounceTimer);
        await record.watcher.close();
        this.active.delete(id);
      }
    }

    for (const spec of watchers) {
      if (this.active.has(spec.id)) continue;
      await this.activate(spec);
    }
  }

  async activate(rawSpec) {
    const input = watcherInputSchema.parse(rawSpec);
    assertAllowedCommand(input.command, config.allowedCommands);
    const { repositoryRoot, cwd: watchPath } = await resolveRepositoryPath(
      config.repositoryStorageRoot,
      input.repositoryId,
      input.path,
    );
    await resolveRepositoryPath(
      config.repositoryStorageRoot,
      input.repositoryId,
      input.cwd,
    );
    const ignoredSegments = new Set([
      '.git',
      'node_modules',
      '.venv',
      'venv',
      '__pycache__',
      '.pytest_cache',
      '.mypy_cache',
      'dist',
      'build',
    ]);
    const watcher = chokidar.watch(watchPath, {
      ignoreInitial: true,
      awaitWriteFinish: { stabilityThreshold: 300, pollInterval: 100 },
      ignored: (candidate) => {
        const relative = candidate.slice(repositoryRoot.length);
        return relative.split(/[\\/]/).some((segment) => ignoredSegments.has(segment));
      },
    });
    const record = {
      watcher,
      serialized: JSON.stringify(rawSpec),
      debounceTimer: null,
      lastEvent: null,
    };
    const schedule = (eventName, filePath) => {
      record.lastEvent = { eventName, filePath };
      clearTimeout(record.debounceTimer);
      record.debounceTimer = setTimeout(async () => {
        const event = record.lastEvent;
        try {
          await enqueueTask(
            this.queue,
            {
              type: 'command',
              workspaceId: input.workspaceId,
              repositoryId: input.repositoryId,
              command: input.command,
              args: input.args,
              cwd: input.cwd,
              environment: {
                ...input.environment,
                AMOSCLAUD_PROJECT_WATCHER_ID: rawSpec.id,
                AMOSCLAUD_PROJECT_FILE_EVENT: event?.eventName || 'change',
                AMOSCLAUD_PROJECT_CHANGED_PATH: event?.filePath || '',
              },
              timeoutMs: input.timeoutMs,
              source: { type: 'watcher', id: rawSpec.id },
            },
            { jobId: `${rawSpec.id}-${Date.now()}` },
          );
        } catch (error) {
          console.error(`Watcher ${rawSpec.id} could not enqueue a task:`, error);
        }
      }, input.debounceMs);
      record.debounceTimer.unref();
    };
    watcher.on('all', schedule);
    watcher.on('error', (error) => console.error(`Watcher ${rawSpec.id} failed:`, error));
    this.active.set(rawSpec.id, record);
  }
}

export async function startWorker() {
  const problems = readinessProblems();
  if (problems.length) {
    throw new Error(`Control-plane worker is not ready: ${problems.join('; ')}`);
  }
  const redis = createRedis();
  await redis.ping();
  const queue = createTaskQueue(createRedis());
  const worker = new Worker(
    config.queueName,
    (job) => processTask(redis, job),
    {
      connection: createRedis(),
      concurrency: config.workerConcurrency,
    },
  );
  const watchers = new WatcherSupervisor(redis, queue);
  await watchers.start();

  worker.on('error', (error) => console.error('Amosclaud worker error:', error));
  worker.on('failed', (job, error) => {
    console.error(`Amosclaud task ${job?.id ?? 'unknown'} failed:`, error.message);
  });

  const close = async () => {
    await watchers.stop();
    await worker.close();
    await queue.close();
    await redis.quit();
  };
  process.once('SIGTERM', () => close().finally(() => process.exit(0)));
  process.once('SIGINT', () => close().finally(() => process.exit(0)));
  return { worker, queue, redis, watchers };
}

if (import.meta.url === `file://${process.argv[1]}`) {
  startWorker()
    .then(() => console.log('Amosclaud control-plane worker started'))
    .catch((error) => {
      console.error(error);
      process.exitCode = 1;
    });
}
