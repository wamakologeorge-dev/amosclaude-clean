import { z } from 'zod';

const workspaceId = z.string().regex(/^ws_[a-z0-9]{12,48}$/);
const repositoryId = z.number().int().positive();
const command = z.string().min(1).max(80);
const argument = z.string().max(2_000).refine((value) => !value.includes('\0'));
const relativePath = z.string().min(1).max(1_000).default('.');
const environment = z.record(z.string(), z.string().max(4_096)).default({});

export const commandTaskSchema = z.object({
  type: z.literal('command'),
  workspaceId,
  repositoryId,
  command,
  args: z.array(argument).max(100).default([]),
  cwd: relativePath,
  environment,
  timeoutMs: z.number().int().min(1_000).max(3_600_000).default(300_000),
  source: z
    .object({
      type: z.enum(['api', 'watcher', 'agent']).default('api'),
      id: z.string().max(200).optional(),
    })
    .default({ type: 'api' }),
});

export const runtimeStartTaskSchema = z.object({
  type: z.literal('runtime.start'),
  workspaceId,
  repositoryId,
  ownerId: z.number().int().positive(),
  environment,
});

export const runtimeStopTaskSchema = z.object({
  type: z.literal('runtime.stop'),
  workspaceId,
});

export const runtimeStatusTaskSchema = z.object({
  type: z.literal('runtime.status'),
  workspaceId,
});

export const taskSchema = z.discriminatedUnion('type', [
  commandTaskSchema,
  runtimeStartTaskSchema,
  runtimeStopTaskSchema,
  runtimeStatusTaskSchema,
]);

export const watcherInputSchema = z.object({
  workspaceId,
  repositoryId,
  path: relativePath,
  command,
  args: z.array(argument).max(100).default([]),
  cwd: relativePath,
  environment,
  timeoutMs: z.number().int().min(1_000).max(3_600_000).default(300_000),
  debounceMs: z.number().int().min(100).max(60_000).default(1_000),
});

export const skillPackageManifestSchema = z.object({
  skills: z
    .array(
      z.object({
        id: z.string().regex(/^[a-z0-9][a-z0-9._-]{1,79}$/),
        source: z.string().min(1).max(1_000),
        target: z.string().min(1).max(1_000).optional(),
      }),
    )
    .min(1),
});
