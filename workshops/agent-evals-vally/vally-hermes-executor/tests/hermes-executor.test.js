// Integration tests: run the real executor against scripts/fake_hermes.py (no model, no
// network). Skipped when the PersonaDesk Python environment is not installed.
import assert from "node:assert/strict";
import { existsSync, mkdtempSync, readdirSync, readFileSync, rmSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import { after, test } from "node:test";
import { fileURLToPath } from "node:url";
import { HermesExecutor, resolveJob, validateHermesConfig } from "../src/hermes-executor.js";

const personadesk = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..", "..",
  "personal-agent-multilora");
const venvPython = path.join(personadesk, ".venv", process.platform === "win32" ? "Scripts/python.exe" : "bin/python");
const skip = !existsSync(venvPython) && !process.env.PERSONADESK_PYTHON
  ? "PersonaDesk .venv not installed (see workshops/personal-agent-multilora/README.md)" : false;

const executor = new HermesExecutor();
const workDirs = [];
after(async () => {
  await executor.shutdown();
  for (const dir of workDirs) rmSync(dir, { recursive: true, force: true });
});

function trial(env = {}, extra = {}) {
  const workDir = mkdtempSync(path.join(os.tmpdir(), "vally-hermes-test-"));
  workDirs.push(workDir);
  const stimulus = { name: "t", prompt: "Draft a reply.", tags: { fixture: "priya-002", profile: "pd-priya" } };
  return executor.execute(stimulus, { workDir, timeout: 60_000, env, executorConfig: { hermes_bin: "fake" }, ...extra });
}

test("config validation rejects unknown keys and non-strings", () => {
  assert.throws(() => validateHermesConfig({ profle: "pd-priya" }), /unknown key 'profle'/);
  assert.throws(() => validateHermesConfig({ profile: 3 }), /non-empty string/);
  validateHermesConfig({ profile: "pd-priya", hermes_bin: "fake" });
});

test("a stimulus without a fixture tag is rejected before anything runs", () => {
  assert.throws(() => resolveJob({ name: "x", prompt: "p" }, { profile: "pd-priya" }), /tags.fixture/);
});

test("fake ok run: completed trajectory and the stored draft in the workspace", { skip }, async () => {
  const t = await trial();
  assert.equal(t.endReason, "completed");
  assert.equal(t.metrics.toolCallCount, 4);
  assert.equal(t.metadata.executor, "hermes");
  const job = t.events.find((e) => e.type === "custom");
  assert.equal(job.data.status, "awaiting_review");
  assert.match(job.data.artifact_hash, /^sha256:/);
  const draft = readFileSync(path.join(t.workDir, "personadesk-out", "draft.txt"), "utf8");
  assert.match(draft, /billing team/);
});

test("fake failure is an agent outcome (graded), not an infrastructure error", { skip }, async () => {
  const t = await trial({ FAKE_HERMES_MODE: "nonzero" });
  assert.equal(t.endReason, "completed");
  assert.ok(t.events.some((e) => e.type === "error"));
  assert.equal(t.events.find((e) => e.type === "custom").data.status, "failed");
});

test("time limit: partial trajectory, agent_timeout, and the PersonaDesk lock is released", { skip }, async () => {
  const started = Date.now();
  const t = await trial({ FAKE_HERMES_MODE: "sleep" }, { maxAgentDurationMs: 3000 });
  assert.ok(Date.now() - started < 30_000, "the worker was stopped promptly");
  assert.equal(t.endReason, "agent_timeout");
  assert.ok(!t.events.some((e) => e.type === "turn_end"));
  assert.ok(t.events.some((e) => e.type === "error" && e.data.type === "timeout"));
  const locks = path.join(personadesk, "artifacts", "locks");
  assert.deepEqual(existsSync(locks) ? readdirSync(locks) : [], []);
});

test("an unknown profile is a non-retryable configuration error", { skip }, async () => {
  const workDir = mkdtempSync(path.join(os.tmpdir(), "vally-hermes-test-"));
  workDirs.push(workDir);
  const stimulus = { name: "t", prompt: "p", tags: { fixture: "priya-002", profile: "pd-nobody" } };
  await assert.rejects(executor.execute(stimulus, { workDir, timeout: 60_000, executorConfig: {} }),
    (err) => err.retryable === false && /configuration problem/.test(err.message));
});
