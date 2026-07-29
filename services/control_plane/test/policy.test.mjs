import assert from 'node:assert/strict';
import { mkdtemp, mkdir, symlink } from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import test from 'node:test';

import {
  assertAllowedCommand,
  assertRelativeWorkspacePath,
  parseAllowedCommands,
  resolveRepositoryPath,
  sanitizeEnvironment,
  splitLogLines,
} from '../src/policy.mjs';

test('command policy accepts only configured executable names', () => {
  const allowed = parseAllowedCommands('git,npm');
  assert.equal(assertAllowedCommand('git', allowed), 'git');
  assert.throws(() => assertAllowedCommand('/bin/sh', allowed), /simple executable/);
  assert.throws(() => assertAllowedCommand('python', allowed), /not allowed/);
});

test('environment sanitizer does not inherit platform secrets', () => {
  const result = sanitizeEnvironment(
    {
      PROJECT_NAME: 'demo',
      CI: 'true',
      DATABASE_URL: 'secret',
      OPENAI_API_KEY: 'secret',
    },
    {
      PATH: '/usr/bin',
      HOME: '/home/node',
      AMOSCLAUD_CONTROL_PLANE_TOKEN: 'secret',
    },
  );
  assert.deepEqual(result, {
    PATH: '/usr/bin',
    HOME: '/home/node',
    PROJECT_NAME: 'demo',
    CI: 'true',
  });
});

test('relative workspace paths reject traversal', () => {
  assert.equal(assertRelativeWorkspacePath('src/../test'), 'test');
  assert.throws(() => assertRelativeWorkspacePath('../outside'), /cannot leave/);
  assert.throws(() => assertRelativeWorkspacePath('/tmp'), /relative/);
});

test('workspace resolution rejects symlink escape', async () => {
  const base = await mkdtemp(path.join(os.tmpdir(), 'amosclaud-policy-'));
  const storage = path.join(base, 'repositories');
  const repository = path.join(storage, '42');
  const outside = path.join(base, 'outside');
  await mkdir(repository, { recursive: true });
  await mkdir(path.join(repository, 'src'));
  await mkdir(outside);
  await symlink(outside, path.join(repository, 'escape'));

  const resolved = await resolveRepositoryPath(storage, 42, 'src');
  assert.equal(resolved.cwd, path.join(repository, 'src'));
  await assert.rejects(
    resolveRepositoryPath(storage, 42, 'escape'),
    /symbolic link outside/,
  );
});

test('log splitting normalizes terminal newlines', () => {
  assert.deepEqual(splitLogLines('one\r\ntwo\rthree\n'), ['one', 'two', 'three']);
});
