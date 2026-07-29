import { realpath, stat } from 'node:fs/promises';
import path from 'node:path';

export const DEFAULT_ALLOWED_COMMANDS = Object.freeze([
  'git',
  'npm',
  'npx',
  'pnpm',
  'yarn',
  'node',
  'python',
  'python3',
  'pytest',
  'uv',
  'ruff',
  'mypy',
  'make',
  'go',
  'cargo',
]);

const SAFE_ENVIRONMENT_PREFIXES = Object.freeze([
  'AMOSCLAUD_PROJECT_',
  'PROJECT_',
  'CI_',
]);

const SAFE_ENVIRONMENT_NAMES = new Set([
  'CI',
  'NODE_ENV',
  'PYTHONPATH',
  'PYTHONUNBUFFERED',
  'FORCE_COLOR',
  'NO_COLOR',
]);

const INHERITED_ENVIRONMENT_NAMES = Object.freeze([
  'PATH',
  'HOME',
  'USER',
  'LOGNAME',
  'LANG',
  'LC_ALL',
  'TERM',
  'TMPDIR',
  'TEMP',
  'TMP',
]);

export function parseAllowedCommands(value) {
  const items = String(value ?? '')
    .split(',')
    .map((item) => item.trim())
    .filter(Boolean);
  return new Set(items.length ? items : DEFAULT_ALLOWED_COMMANDS);
}

export function assertAllowedCommand(command, allowedCommands) {
  const candidate = String(command ?? '').trim();
  if (!/^[A-Za-z0-9._+-]{1,80}$/.test(candidate)) {
    throw new Error('Command must be a simple executable name without a path.');
  }
  if (!allowedCommands.has(candidate)) {
    throw new Error(`Command is not allowed by policy: ${candidate}`);
  }
  return candidate;
}

export function sanitizeEnvironment(values, inherited = process.env) {
  const safe = {};
  for (const name of INHERITED_ENVIRONMENT_NAMES) {
    const value = inherited[name];
    if (typeof value === 'string' && value.length <= 4096 && !value.includes('\0')) {
      safe[name] = value;
    }
  }

  for (const [rawName, rawValue] of Object.entries(values ?? {})) {
    const name = String(rawName);
    const value = String(rawValue);
    const allowed =
      SAFE_ENVIRONMENT_NAMES.has(name) ||
      SAFE_ENVIRONMENT_PREFIXES.some((prefix) => name.startsWith(prefix));
    if (!allowed) continue;
    if (!/^[A-Z_][A-Z0-9_]{0,99}$/.test(name)) continue;
    if (value.length > 4096 || value.includes('\0')) continue;
    safe[name] = value;
  }
  return safe;
}

export function assertRelativeWorkspacePath(value, label = 'path') {
  const candidate = String(value ?? '.').trim() || '.';
  if (candidate.includes('\0') || path.isAbsolute(candidate)) {
    throw new Error(`${label} must be a relative workspace path.`);
  }
  const normalized = path.normalize(candidate);
  if (normalized === '..' || normalized.startsWith(`..${path.sep}`)) {
    throw new Error(`${label} cannot leave the repository workspace.`);
  }
  return normalized;
}

function isInside(root, candidate) {
  const relative = path.relative(root, candidate);
  return relative === '' || (!relative.startsWith('..') && !path.isAbsolute(relative));
}

export async function resolveRepositoryPath(storageRoot, repositoryId, relativePath = '.') {
  if (!Number.isSafeInteger(repositoryId) || repositoryId <= 0) {
    throw new Error('repositoryId must be a positive integer.');
  }
  const configuredRoot = path.resolve(String(storageRoot));
  const rootReal = await realpath(configuredRoot);
  const repository = path.resolve(rootReal, String(repositoryId));
  const repositoryReal = await realpath(repository);
  if (!isInside(rootReal, repositoryReal)) {
    throw new Error('Repository storage resolved outside the configured storage root.');
  }
  const repositoryStats = await stat(repositoryReal);
  if (!repositoryStats.isDirectory()) {
    throw new Error('Repository storage is not a directory.');
  }

  const normalized = assertRelativeWorkspacePath(relativePath, 'cwd');
  const candidate = path.resolve(repositoryReal, normalized);
  if (!isInside(repositoryReal, candidate)) {
    throw new Error('cwd resolved outside the repository workspace.');
  }
  const candidateReal = await realpath(candidate);
  if (!isInside(repositoryReal, candidateReal)) {
    throw new Error('cwd follows a symbolic link outside the repository workspace.');
  }
  const candidateStats = await stat(candidateReal);
  if (!candidateStats.isDirectory()) {
    throw new Error('cwd is not a directory.');
  }
  return { repositoryRoot: repositoryReal, cwd: candidateReal };
}

export function publicTaskData(data) {
  if (!data || typeof data !== 'object') return data;
  const copy = { ...data };
  if (copy.environment && typeof copy.environment === 'object') {
    copy.environmentKeys = Object.keys(copy.environment).sort();
    delete copy.environment;
  }
  return copy;
}

export function splitLogLines(chunk) {
  return String(chunk ?? '')
    .replace(/\r\n/g, '\n')
    .replace(/\r/g, '\n')
    .split('\n')
    .filter((line) => line.length > 0);
}
