import { readFile } from 'node:fs/promises';

const packageJson = JSON.parse(
  await readFile(new URL('../package.json', import.meta.url), 'utf8'),
);

const forbiddenLifecycleScripts = ['preinstall', 'install', 'postinstall'];
for (const script of forbiddenLifecycleScripts) {
  if (packageJson.scripts?.[script]) {
    throw new Error(`Forbidden lifecycle script: ${script}`);
  }
}

const dependencyGroups = ['dependencies', 'devDependencies', 'optionalDependencies'];
const unsafeVersion = /^(?:\^|~|>|<|=|\*|latest$|next$|beta$|alpha$|canary$|git\+|https?:|file:|workspace:)/i;
for (const group of dependencyGroups) {
  for (const [name, version] of Object.entries(packageJson[group] ?? {})) {
    if (typeof version !== 'string' || unsafeVersion.test(version)) {
      throw new Error(`${group}.${name} must use an exact registry version, got ${version}`);
    }
  }
}

if (packageJson.private !== true) {
  throw new Error('The control-plane package must remain private.');
}

console.log('npm supply-chain policy passed');
