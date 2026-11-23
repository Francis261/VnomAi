import { spawn } from 'node:child_process';
import fs from 'node:fs/promises';
import path from 'node:path';

const root = process.cwd();
const handoffMinutes = Math.max(15, Math.min(330, Number(process.env.MICODE_HANDOFF_MINUTES || 270)));
const startedAt = Date.now();
const handoffAt = startedAt + handoffMinutes * 60_000;
const sessionId = process.env.MICODE_SESSION_ID || 'unknown';
const token = process.env.MICODE_AGENT_TOKEN || '';
if (!token || token.length < 32) throw new Error('MICODE_AGENT_TOKEN is missing or too short. Configure the repository Actions secret before starting the runtime.');
const branch = `micode/agent/${sessionId.replace(/[^a-zA-Z0-9._-]/g, '-')}`;
const memoryDir = path.join(root, 'MiCode', 'memory');
const stateDir = path.join(root, 'MiCode', 'state');
const checkpointPath = path.join(stateDir, 'checkpoint.json');
let tunnel;
let agentServer;
let shuttingDown = false;

function command(bin, args) {
  return new Promise((resolve, reject) => {
    const child = spawn(bin, args, { cwd: root, env: process.env, stdio: ['ignore', 'pipe', 'pipe'] });
    let stdout = ''; let stderr = '';
    child.stdout.on('data', chunk => { stdout += chunk; process.stdout.write(chunk); });
    child.stderr.on('data', chunk => { stderr += chunk; process.stderr.write(chunk); });
    child.once('error', reject);
    child.once('close', code => code === 0 ? resolve(stdout) : reject(new Error(`${bin} ${args.join(' ')} exited ${code}: ${stderr.slice(-3000)}`)));
  });
}

async function writeCheckpoint(status, extra = {}) {
  const data = {
    schemaVersion: 1, sessionId, runId: process.env.GITHUB_RUN_ID || null,
    runAttempt: Number(process.env.GITHUB_RUN_ATTEMPT || 1), status,
    startedAt: new Date(startedAt).toISOString(), handoffAt: new Date(handoffAt).toISOString(),
    updatedAt: new Date().toISOString(), lastCommit: process.env.GITHUB_SHA || null, ...extra,
  };
  const temp = checkpointPath + '.tmp';
  await fs.writeFile(temp, JSON.stringify(data, null, 2) + '\n', { mode: 0o600 });
  await fs.rename(temp, checkpointPath);
}

async function publishRuntimeStatus(status, extra = {}) {
  const repository = process.env.GITHUB_REPOSITORY || '';
  const [owner, repo] = repository.split('/');
  const token = process.env.GITHUB_TOKEN;
  if (!owner || !repo || !token) {
    console.warn('GitHub runtime status publishing is unavailable.');
    return;
  }
  const file = 'MiCode/state/runtime.json';
  const api = `https://api.github.com/repos/${owner}/${repo}/contents/${file}`;
  const headers = {
    authorization: `Bearer ${token}`,
    accept: 'application/vnd.github+json',
    'content-type': 'application/json',
    'x-github-api-version': '2022-11-28',
  };
  const branchRef = process.env.GITHUB_REF_NAME || 'main';
  let sha;
  const current = await fetch(api + '?ref=' + encodeURIComponent(branchRef), { headers });
  if (current.ok) sha = (await current.json()).sha;
  else if (current.status !== 404) throw new Error(`Could not read runtime status (${current.status}).`);
  const state = {
    schemaVersion: 1, sessionId, runId: process.env.GITHUB_RUN_ID || null,
    runAttempt: Number(process.env.GITHUB_RUN_ATTEMPT || 1), status,
    tunnelUrl: extra.tunnelUrl || null,
    handoffAt: new Date(handoffAt).toISOString(),
    updatedAt: new Date().toISOString(),
  };
  const response = await fetch(api, {
    method: 'PUT', headers,
    body: JSON.stringify({
      message: `chore(micode): update runtime status (${status})`,
      content: Buffer.from(JSON.stringify(state, null, 2)).toString('base64'),
      branch: branchRef,
      ...(sha ? { sha } : {}),
    }),
  });
  if (!response.ok) throw new Error(`Could not publish runtime status (${response.status}): ${(await response.text()).slice(0, 500)}`);
}

async function callback(event, payload = {}) {
  const base = process.env.MICODE_CALLBACK_URL;
  const callbackToken = process.env.MICODE_CALLBACK_TOKEN;
  if (!base || !callbackToken) {
    console.warn('MiCode callback is not configured; control-plane notifications are disabled.');
    return;
  }
  const response = await fetch(new URL('/v1/runner/events', base), {
    method: 'POST',
    headers: { authorization: `Bearer ${callbackToken}`, 'content-type': 'application/json' },
    body: JSON.stringify({ event, sessionId, runId: process.env.GITHUB_RUN_ID, runAttempt: Number(process.env.GITHUB_RUN_ATTEMPT || 1), ...payload }),
  });
  if (!response.ok) throw new Error(`MiCode control-plane callback failed (${response.status}).`);
}

async function publishCheckpoint(reason) {
  await writeCheckpoint('handoff-preparing', { reason });
  const continuation = [
    '# Agent continuation', '',
    `- Session: ${sessionId}`,
    `- Run: ${process.env.GITHUB_RUN_ID || 'unknown'}`,
    `- Checkpoint time: ${new Date().toISOString()}`,
    `- Reason: ${reason}`, '',
    '## Instructions for the next run',
    '1. Read project-context.md, completed-tasks.md, current-task.md, todo.md, and decisions.md.',
    '2. Inspect git status and the actual repository state; do not assume every reported change was completed.',
    '3. Continue from the first incomplete TODO and verify work before marking it complete.',
    '4. Never overwrite unrelated user changes or expose secrets.', '',
  ].join('\n');
  await fs.writeFile(path.join(memoryDir, 'continuation.md'), continuation);
  await writeCheckpoint('handoff-ready', { reason });
  await command('git', ['config', 'user.name', 'MiCode Agent']);
  await command('git', ['config', 'user.email', 'agent@micode.local']);
  await command('git', ['switch', '-C', branch]);
  await command('git', ['add', '-A']);
  const status = await command('git', ['status', '--porcelain']);
  if (status.trim()) await command('git', ['commit', '-m', `chore(micode): checkpoint ${sessionId} before handoff`]);
  await command('git', ['push', '--set-upstream', 'origin', branch]);
  const commit = (await command('git', ['rev-parse', 'HEAD'])).trim();
  await writeCheckpoint('pushed', { reason, lastCommit: commit, branch });
  await callback('checkpoint.pushed', { commit, branch, reason, handoffAt: new Date(handoffAt).toISOString() });
  return commit;
}

async function startServer() {
  agentServer = spawn('node', ['MiCode/runtime/agent-server.js'], {
    cwd: root,
    env: { ...process.env, PORT: '8788', MICODE_SERVER_TOKEN: token, MICODE_RUNTIME_MODE: '1', MICODE_PUBLIC_URL: '' },
    stdio: ['ignore', 'pipe', 'pipe'],
  });
  agentServer.stdout.on('data', chunk => process.stdout.write(chunk));
  agentServer.stderr.on('data', chunk => process.stderr.write(chunk));
  for (let i = 0; i < 30; i++) {
    if (agentServer.exitCode !== null) throw new Error('MiCode agent API exited before becoming healthy.');
    try {
      const response = await fetch('http://127.0.0.1:8788/health');
      if (response.ok) return;
    } catch {}
    await new Promise(resolve => setTimeout(resolve, 1000));
  }
  throw new Error('MiCode agent API did not become healthy within 30 seconds.');
}

async function startTunnel() {
  tunnel = spawn('cloudflared', ['tunnel', '--no-autoupdate', '--url', 'http://127.0.0.1:8788'], { stdio: ['ignore', 'pipe', 'pipe'] });
  let buffer = '';
  const findUrl = chunk => {
    buffer = (buffer + chunk.toString()).slice(-12000);
    const match = buffer.match(/https:\/\/[a-z0-9-]+\.trycloudflare\.com/i);
    if (match && !tunnel.url) {
      tunnel.url = match[0];
      callback('tunnel.ready', { url: tunnel.url, handoffAt: new Date(handoffAt).toISOString() }).catch(error => console.error(error));
      console.log(`MiCode tunnel ready: ${tunnel.url}`);
    }
  };
  tunnel.stdout.on('data', findUrl); tunnel.stderr.on('data', findUrl);
  tunnel.once('exit', code => {
    if (!shuttingDown) {
      console.error(`Cloudflare tunnel exited (${code}); runtime is no longer reachable.`);
      publishRuntimeStatus('tunnel-lost').catch(console.error);
      callback('tunnel.lost', { code }).catch(console.error);
    }
  });
  for (let i = 0; i < 60 && !tunnel.url; i++) await new Promise(resolve => setTimeout(resolve, 1000));
  if (!tunnel.url) throw new Error('Cloudflare Quick Tunnel did not provide a URL within 60 seconds.');
}

async function shutdown(reason) {
  if (shuttingDown) return;
  shuttingDown = true;
  console.log(`MiCode runtime handoff: ${reason}`);
  try {
    const commit = await publishCheckpoint(reason);
    await callback('handoff.ready', { commit, branch, reason });
  } catch (error) {
    console.error('Checkpoint push failed; refusing to report a successful handoff:', error);
    await callback('handoff.failed', { error: error.message }).catch(console.error);
    process.exitCode = 1;
  }
  tunnel?.kill('SIGTERM');
  agentServer?.kill('SIGTERM');
  process.exit(process.exitCode || 0);
}

process.on('SIGTERM', () => void shutdown('runner-termination'));
process.on('SIGINT', () => void shutdown('runner-interruption'));

await fs.mkdir(memoryDir, { recursive: true });
await fs.mkdir(stateDir, { recursive: true });
await command('git', ['switch', '-C', branch]);
await startServer();
await startTunnel();
await writeCheckpoint('running', { tunnelUrl: tunnel.url, branch });
await publishRuntimeStatus('ready', { tunnelUrl: tunnel.url });
await callback('runtime.ready', { url: tunnel.url, handoffAt: new Date(handoffAt).toISOString() });
console.log(`MiCode runtime active for ${handoffMinutes} minutes. Session ${sessionId}.`);
const warningAt = handoffAt - 30 * 60_000;
setTimeout(() => callback('handoff.warning', { remainingMs: handoffAt - Date.now() }).catch(console.error), Math.max(0, warningAt - Date.now()));
setTimeout(() => void shutdown('scheduled-handoff'), Math.max(0, handoffAt - Date.now()));
