import { spawnSync } from 'node:child_process';
import { packageCommandFailure } from './package_command_failure.mjs';

// Identical linux/amd64 Docker Official Image manifests, verified in both
// publisher registries. No mutable tags or arbitrary fallback image are used.
const digest = 'sha256:d6aa754f16b3197301076f047b5def2f02ea1dbbc2ca920407d46d7ec7f87b20';
const registries = ['public.ecr.aws/docker/library/node', 'docker.io/library/node'];

export function buildReviewedWebImage(buildArgs, spawn = spawnSync) {
  for (let index = 0; index < registries.length; index++) {
    const args = ['build', ...buildArgs.slice(0, -1), '--build-arg',
      `NODE_BASE_IMAGE=${registries[index]}@${digest}`, buildArgs.at(-1)];
    const result = spawn('docker', args, { encoding: 'utf8', timeout: 240000, maxBuffer: 256 * 1024 });
    if (!result.error && result.status === 0) return { registry: index === 0 ? 'ecr' : 'hub', mirrorFallback: index > 0 };
    const failure = packageCommandFailure(result);
    // Retry only a registry quota refusal; build/context/runtime failures and
    // resource limits retain their actual failure instead of starting over.
    if (index === 0 && failure === 'registry_rate_limit') continue;
    throw Error(`docker failed (${result.status ?? 'no exit code'}; ${failure})`);
  }
}
