import { createRequire } from 'node:module';
import { copyFile, mkdir, readFile, realpath, rename, stat } from 'node:fs/promises';
import path from 'node:path';

import { config } from './config.mjs';
import { skillPackageManifestSchema } from './contracts.mjs';
import { assertRelativeWorkspacePath } from './policy.mjs';

const require = createRequire(import.meta.url);

function isInside(root, candidate) {
  const relative = path.relative(root, candidate);
  return relative === '' || (!relative.startsWith('..') && !path.isAbsolute(relative));
}

async function findPackageRoot(entryFile) {
  let directory = path.dirname(entryFile);
  while (true) {
    const packageJsonPath = path.join(directory, 'package.json');
    try {
      const packageJson = JSON.parse(await readFile(packageJsonPath, 'utf8'));
      return { directory, packageJsonPath, packageJson };
    } catch (error) {
      if (error.code !== 'ENOENT' && !(error instanceof SyntaxError)) throw error;
    }
    const parent = path.dirname(directory);
    if (parent === directory) throw new Error(`Could not locate package.json for ${entryFile}`);
    directory = parent;
  }
}

async function packageMetadata(packageName) {
  let entry;
  try {
    entry = require.resolve(packageName);
  } catch {
    entry = require.resolve(`${packageName}/package.json`);
  }
  return findPackageRoot(entry);
}

export async function syncSkillPackages(packageNames, outputRoot) {
  const destinationRoot = path.resolve(outputRoot);
  await mkdir(destinationRoot, { recursive: true });
  const destinationReal = await realpath(destinationRoot);
  const installed = [];

  for (const packageName of packageNames) {
    const metadata = await packageMetadata(packageName);
    const packageRoot = await realpath(metadata.directory);
    const manifest = skillPackageManifestSchema.parse(metadata.packageJson.amosclaud);

    for (const skill of manifest.skills) {
      const sourceRelative = assertRelativeWorkspacePath(skill.source, 'skill source');
      const sourceCandidate = path.resolve(packageRoot, sourceRelative);
      const sourceReal = await realpath(sourceCandidate);
      if (!isInside(packageRoot, sourceReal)) {
        throw new Error(`Skill source escapes npm package ${packageName}: ${skill.source}`);
      }
      const sourceStats = await stat(sourceReal);
      if (!sourceStats.isFile()) {
        throw new Error(`Skill source is not a file: ${packageName}/${skill.source}`);
      }

      const targetRelative = assertRelativeWorkspacePath(
        skill.target || path.join(skill.id, 'SKILL.md'),
        'skill target',
      );
      const target = path.resolve(destinationReal, targetRelative);
      if (!isInside(destinationReal, target)) {
        throw new Error(`Skill target escapes the output root: ${targetRelative}`);
      }
      await mkdir(path.dirname(target), { recursive: true });
      const temporary = `${target}.tmp-${process.pid}-${Date.now()}`;
      await copyFile(sourceReal, temporary);
      await rename(temporary, target);
      installed.push({ package: packageName, skill: skill.id, target });
    }
  }
  return installed;
}

if (import.meta.url === `file://${process.argv[1]}`) {
  syncSkillPackages(config.skillPackages, config.skillOutputRoot)
    .then((installed) => {
      console.log(
        JSON.stringify(
          {
            ok: true,
            packages: config.skillPackages,
            installed,
          },
          null,
          2,
        ),
      );
    })
    .catch((error) => {
      console.error(error);
      process.exitCode = 1;
    });
}
