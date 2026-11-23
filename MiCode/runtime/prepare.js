import fs from 'node:fs/promises';
import path from 'node:path';

const root = process.cwd();
const memory = path.join(root, 'MiCode', 'memory');
const state = path.join(root, 'MiCode', 'state');
await fs.mkdir(memory, { recursive: true });
await fs.mkdir(state, { recursive: true });

const defaults = {
  'project-context.md': '# Project context\n\nDescribe the project, its architecture, constraints, and conventions.\n',
  'completed-tasks.md': '# Completed tasks\n\n',
  'current-task.md': '# Current task\n\nNo active task recorded.\n',
  'todo.md': '# TODO\n\n- [ ] Review the project and identify the next task\n',
  'decisions.md': '# Decisions\n\n',
  'continuation.md': '# Agent continuation\n\nNo previous checkpoint exists. Inspect the repository before making changes.\n',
};
for (const [name, content] of Object.entries(defaults)) {
  const file = path.join(memory, name);
  try { await fs.access(file); } catch { await fs.writeFile(file, content, { flag: 'wx' }); }
}

const checkpointFile = path.join(state, 'checkpoint.json');
try { await fs.access(checkpointFile); } catch {
  await fs.writeFile(checkpointFile, JSON.stringify({
    schemaVersion: 1,
    sessionId: process.env.MICODE_SESSION_ID || null,
    runId: process.env.GITHUB_RUN_ID || null,
    status: 'initialized',
    updatedAt: new Date().toISOString(),
    lastCommit: process.env.GITHUB_SHA || null,
  }, null, 2) + '\n');
}
console.log('MiCode continuation state is ready.');
