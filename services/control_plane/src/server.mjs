import Fastify from 'fastify';
import { ZodError, z } from 'zod';

import { config, readinessProblems } from './config.mjs';
import { taskSchema, watcherInputSchema } from './contracts.mjs';
import {
  authenticateToken,
  bearerToken,
  createRedis,
  createTaskQueue,
  createWatcher,
  deleteWatcher,
  enqueueTask,
  getTaskLogs,
  listWatchers,
  publicTaskData,
  requestCancellation,
  runtimeClient,
  taskEventChannel,
} from './platform.mjs';
import { assertAllowedCommand, assertRelativeWorkspacePath } from './policy.mjs';

const idParamsSchema = z.object({ id: z.string().min(1).max(200) });
const logsQuerySchema = z.object({
  after: z.coerce.number().int().min(0).default(0),
});

export function buildServer() {
  const app = Fastify({
    logger: {
      level: process.env.LOG_LEVEL?.trim() || 'info',
      redact: {
        paths: [
          'req.headers.authorization',
          'request.headers.authorization',
          '*.token',
          '*.runtimeToken',
          '*.environment.*',
        ],
        censor: '[redacted]',
      },
    },
    bodyLimit: 256 * 1024,
    requestTimeout: 30_000,
  });
  const redis = createRedis();
  const queue = createTaskQueue(createRedis());

  const requireServiceToken = async (request, reply) => {
    if (!config.token) {
      return reply.code(503).send({
        error: 'not_configured',
        detail: 'AMOSCLAUD_CONTROL_PLANE_TOKEN is not configured.',
      });
    }
    const token = bearerToken(request.headers.authorization);
    if (!authenticateToken(token)) {
      return reply.code(401).send({
        error: 'invalid_authorization',
        detail: 'A valid private control-plane bearer token is required.',
      });
    }
  };

  app.setErrorHandler((error, request, reply) => {
    if (error instanceof ZodError) {
      return reply.code(422).send({
        error: 'validation_error',
        detail: error.issues.map((issue) => ({
          path: issue.path.join('.'),
          message: issue.message,
        })),
      });
    }
    request.log.error({ err: error }, 'control-plane request failed');
    const statusCode = Number.isInteger(error.statusCode) ? error.statusCode : 500;
    return reply.code(statusCode).send({
      error: statusCode >= 500 ? 'internal_error' : 'request_error',
      detail:
        statusCode >= 500
          ? 'The Amosclaud control plane could not complete this request.'
          : error.message,
    });
  });

  app.get('/live', async () => ({ ok: true, service: 'amosclaud-control-plane' }));

  app.get('/health', { preHandler: requireServiceToken }, async (_request, reply) => {
    const problems = readinessProblems();
    let redisReady = false;
    try {
      redisReady = (await redis.ping()) === 'PONG';
    } catch (error) {
      problems.push(`Redis is unavailable: ${error.constructor?.name || 'Error'}`);
    }

    let runtime = { configured: runtimeClient.configured(), ok: false };
    if (runtime.configured) {
      try {
        runtime = { configured: true, ok: true, ...(await runtimeClient.health()) };
      } catch (error) {
        runtime = {
          configured: true,
          ok: false,
          detail: error.message,
        };
      }
    }

    const queueCounts = redisReady
      ? await queue.getJobCounts('waiting', 'active', 'completed', 'failed', 'delayed')
      : {};
    const ok = redisReady && problems.length === 0;
    return reply.code(ok ? 200 : 503).send({
      ok,
      service: 'amosclaud-control-plane',
      node: process.version,
      packageManager: 'npm',
      executionMode: config.executionMode,
      watchersEnabled: config.watchersEnabled,
      redisReady,
      runtime,
      queue: queueCounts,
      problems,
    });
  });

  app.post('/v1/tasks', { preHandler: requireServiceToken }, async (request, reply) => {
    const task = taskSchema.parse(request.body);
    if (task.type === 'command') {
      if (config.executionMode !== 'local') {
        return reply.code(409).send({
          error: 'execution_disabled',
          detail: 'Set AMOSCLAUD_EXECUTION_MODE=local on the private worker to run commands.',
        });
      }
      assertAllowedCommand(task.command, config.allowedCommands);
      assertRelativeWorkspacePath(task.cwd, 'cwd');
      task.timeoutMs = Math.min(task.timeoutMs, config.maxCommandTimeoutMs);
    } else if (!runtimeClient.configured()) {
      return reply.code(409).send({
        error: 'runtime_not_configured',
        detail:
          'Set AMOSCLAUD_WORKSPACE_RUNTIME_URL and AMOSCLAUD_WORKSPACE_RUNTIME_TOKEN.',
      });
    }
    const created = await enqueueTask(queue, task);
    return reply.code(202).send({ status: 'queued', task: created });
  });

  app.get('/v1/tasks/:id', { preHandler: requireServiceToken }, async (request, reply) => {
    const { id } = idParamsSchema.parse(request.params);
    const job = await queue.getJob(id);
    if (!job) return reply.code(404).send({ error: 'task_not_found' });
    const state = await job.getState();
    return {
      id: job.id,
      name: job.name,
      state,
      progress: job.progress,
      data: publicTaskData(job.data),
      result: job.returnvalue ?? null,
      failure: job.failedReason || null,
      attemptsMade: job.attemptsMade,
      createdAt: job.timestamp ? new Date(job.timestamp).toISOString() : null,
      processedAt: job.processedOn ? new Date(job.processedOn).toISOString() : null,
      finishedAt: job.finishedOn ? new Date(job.finishedOn).toISOString() : null,
    };
  });

  app.post(
    '/v1/tasks/:id/cancel',
    { preHandler: requireServiceToken },
    async (request, reply) => {
      const { id } = idParamsSchema.parse(request.params);
      const job = await queue.getJob(id);
      if (!job) return reply.code(404).send({ error: 'task_not_found' });
      const state = await job.getState();
      await requestCancellation(redis, id);
      let removed = false;
      if (['waiting', 'delayed', 'prioritized', 'waiting-children'].includes(state)) {
        await job.remove();
        removed = true;
      }
      return reply.code(202).send({
        id,
        previousState: state,
        cancellationRequested: true,
        removed,
      });
    },
  );

  app.get('/v1/tasks/:id/logs', { preHandler: requireServiceToken }, async (request) => {
    const { id } = idParamsSchema.parse(request.params);
    const { after } = logsQuerySchema.parse(request.query);
    return { id, logs: await getTaskLogs(redis, id, after) };
  });

  app.get(
    '/v1/tasks/:id/events',
    { preHandler: requireServiceToken },
    async (request, reply) => {
      const { id } = idParamsSchema.parse(request.params);
      const { after } = logsQuerySchema.parse(request.query);
      const existingJob = await queue.getJob(id);
      if (!existingJob) return reply.code(404).send({ error: 'task_not_found' });

      reply.hijack();
      reply.raw.writeHead(200, {
        'Content-Type': 'text/event-stream',
        'Cache-Control': 'no-cache, no-transform',
        Connection: 'keep-alive',
        'X-Accel-Buffering': 'no',
      });
      reply.raw.write(': connected\n\n');
      for (const entry of await getTaskLogs(redis, id, after)) {
        reply.raw.write(`id: ${entry.sequence}\nevent: log\ndata: ${JSON.stringify(entry)}\n\n`);
      }

      const subscriber = createRedis();
      await subscriber.subscribe(taskEventChannel(id));
      const onMessage = (_channel, message) => {
        if (!reply.raw.destroyed) {
          reply.raw.write(`event: log\ndata: ${message}\n\n`);
        }
      };
      subscriber.on('message', onMessage);
      const heartbeat = setInterval(() => {
        if (!reply.raw.destroyed) reply.raw.write(': heartbeat\n\n');
      }, 15_000);
      heartbeat.unref();

      let cleaned = false;
      const cleanup = async () => {
        if (cleaned) return;
        cleaned = true;
        clearInterval(heartbeat);
        subscriber.off('message', onMessage);
        await subscriber.quit().catch(() => undefined);
      };
      request.raw.once('close', cleanup);
      reply.raw.once('close', cleanup);
    },
  );

  app.get('/v1/watchers', { preHandler: requireServiceToken }, async (_request, reply) => {
    if (!config.watchersEnabled) {
      return reply.code(409).send({ error: 'watchers_disabled' });
    }
    return { watchers: await listWatchers(redis) };
  });

  app.post('/v1/watchers', { preHandler: requireServiceToken }, async (request, reply) => {
    if (!config.watchersEnabled || config.executionMode !== 'local') {
      return reply.code(409).send({
        error: 'watchers_disabled',
        detail: 'Watchers require local execution and a shared repository storage mount.',
      });
    }
    const input = watcherInputSchema.parse(request.body);
    assertAllowedCommand(input.command, config.allowedCommands);
    assertRelativeWorkspacePath(input.path, 'path');
    assertRelativeWorkspacePath(input.cwd, 'cwd');
    input.timeoutMs = Math.min(input.timeoutMs, config.maxCommandTimeoutMs);
    return reply.code(201).send({ watcher: await createWatcher(redis, input) });
  });

  app.delete(
    '/v1/watchers/:id',
    { preHandler: requireServiceToken },
    async (request, reply) => {
      const { id } = idParamsSchema.parse(request.params);
      const deleted = await deleteWatcher(redis, id);
      if (!deleted) return reply.code(404).send({ error: 'watcher_not_found' });
      return reply.code(204).send();
    },
  );

  app.addHook('onClose', async () => {
    await queue.close();
    await redis.quit();
  });

  return app;
}

if (import.meta.url === `file://${process.argv[1]}`) {
  const server = buildServer();
  server
    .listen({ host: config.host, port: config.port })
    .then((address) => server.log.info({ address }, 'Amosclaud control plane listening'))
    .catch((error) => {
      server.log.error({ err: error }, 'Amosclaud control plane failed to start');
      process.exitCode = 1;
    });
}
