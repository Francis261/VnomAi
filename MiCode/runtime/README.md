# Renewable GitHub Actions runtime template

This template is installed into a user's repository as:

- `.github/workflows/micode-agent.yml`
- `MiCode/runtime/prepare.js`
- `MiCode/runtime/agent-server.js`
- `MiCode/runtime/runner.js`

The app creates a random runtime credential, stores it in the device secure store, and uploads it to the repository as the encrypted `MICODE_AGENT_TOKEN` GitHub Actions secret. The runner reads the secret from its environment and uses it to protect the agent API. The credential is never written to repository files, workflow inputs, or runtime status files.

The workflow starts the coding agent on the GitHub Actions runner, exposes its local API through a Cloudflare Quick Tunnel, and publishes `MiCode/state/runtime.json` to the repository default branch using the workflow `GITHUB_TOKEN`. The status file contains the session ID, run ID, status, handoff time, and tunnel URL, but never the authentication credential. The app polls the file, retrieves the matching locally stored credential, and connects directly to the runner tunnel. The default handoff interval is 270 minutes (4 hours 30 minutes).

## Required repository configuration

The app automatically creates the `MICODE_AGENT_TOKEN` Actions secret. Configure `MICODE_AI_BASE_URL` and `MICODE_AI_API_KEY` as repository Actions secrets for the coding model; optionally configure `MICODE_AI_MODEL` as a repository variable. Control-plane callback secrets are optional and are not required for the direct app-to-runner connection.

The user's GitHub token must allow repository Contents write, Actions write, and Actions secrets write. The workflow's built-in `GITHUB_TOKEN` needs Contents write to publish runtime status and checkpoint branches. Do not put PATs or provider keys in tracked files.

## Handoff semantics

The runtime creates a branch named `micode/agent/<session-id>`, writes a continuation checkpoint, commits repository changes, pushes that branch, verifies the push command succeeded, and then reports handoff events when a control plane is configured. It does not force-push and does not push to the user's default branch.

A successful handoff must not be reported unless the push succeeds. A subsequent run must check out the latest checkpoint branch when resuming a session.
