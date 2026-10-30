// Vally executor "hermes": one trial = one PersonaDesk job run through Hermes.
//
// The executor never talks to a model itself. It launches
// scripts/run_personadesk_job.py, which calls PersonaDesk's own run_job (lock, one-time job
// token, `hermes -p <profile> chat --oneshot --format stream-json`, persisted draft). The
// raw stream is then mapped to a Vally trajectory by stream-to-trajectory.js.

import { spawn, spawnSync } from "node:child_process";
import { existsSync } from "node:fs";
import { copyFile, mkdir, readFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { computeMetrics, mergeEnv } from "@microsoft/vally";
import { streamToTrajectoryParts } from "./stream-to-trajectory.js";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const EVALS_WORKSHOP = path.resolve(HERE, "..", "..");
const PERSONADESK = process.env.PERSONADESK_ROOT
  ? path.resolve(process.env.PERSONADESK_ROOT)
  : path.resolve(EVALS_WORKSHOP, "..", "personal-agent-multilora");
const DRIVER = path.join(EVALS_WORKSHOP, "scripts", "run_personadesk_job.py");
const FAKE_HERMES = path.join(PERSONADESK, "scripts", "fake_hermes.py");

export const OUT_DIR_NAME = "personadesk-out";
const CONFIG_KEYS = new Set(["profile", "hermes_bin", "python", "task"]);
const EXIT_TEMPFAIL = 75;
const EXIT_CONFIG = 78;
const BACKSTOP_GRACE_MS = 30_000;

export function validateHermesConfig(config) {
  if (config === undefined || config === null) return;
  if (typeof config !== "object" || Array.isArray(config)) {
    throw new Error("hermes executor config must be a mapping");
  }
  for (const [key, value] of Object.entries(config)) {
    if (!CONFIG_KEYS.has(key)) {
      throw new Error(`hermes executor config: unknown key '${key}' (allowed: ${[...CONFIG_KEYS].join(", ")})`);
    }
    if (typeof value !== "string" || !value) {
      throw new Error(`hermes executor config: '${key}' must be a non-empty string`);
    }
  }
}

function defaultPython() {
  if (process.env.PERSONADESK_PYTHON) return process.env.PERSONADESK_PYTHON;
  const venv = process.platform === "win32"
    ? path.join(PERSONADESK, ".venv", "Scripts", "python.exe")
    : path.join(PERSONADESK, ".venv", "bin", "python");
  return existsSync(venv) ? venv : process.platform === "win32" ? "python" : "python3";
}

function firstTag(tags, key) {
  const value = tags?.[key];
  return Array.isArray(value) ? value[0] : value;
}

/** Resolve one trial's job from executor config plus stimulus tags (tags win). */
export function resolveJob(stimulus, config = {}) {
  const fixture = firstTag(stimulus.tags, "fixture");
  const profile = firstTag(stimulus.tags, "profile") ?? config.profile;
  if (!fixture) throw new Error(`stimulus '${stimulus.name}' needs tags.fixture (e.g. priya-002)`);
  if (!profile) throw new Error(`stimulus '${stimulus.name}' needs tags.profile or executor config.profile`);
  const hermesBin = (config.hermes_bin ?? "fake") === "fake" ? FAKE_HERMES : config.hermes_bin;
  return {
    fixture,
    profile,
    task: firstTag(stimulus.tags, "task") ?? config.task ?? "draft_reply",
    hermesBin,
    python: config.python ?? defaultPython(),
  };
}

function killTree(child) {
  if (child.exitCode !== null || child.pid === undefined) return;
  if (process.platform === "win32") {
    spawnSync("taskkill", ["/pid", String(child.pid), "/T", "/F"], { stdio: "ignore" });
  } else {
    try {
      process.kill(-child.pid, "SIGKILL"); // whole process group (spawned detached)
    } catch {
      child.kill("SIGKILL");
    }
  }
}

async function readIfPresent(file) {
  try {
    return await readFile(file, "utf8");
  } catch (err) {
    if (err?.code === "ENOENT") return undefined;
    throw err;
  }
}

function infraError(message, retryable) {
  const err = new Error(message);
  err.retryable = retryable;
  return err;
}

export class HermesExecutor {
  name = "hermes";
  supportsEnvVars = true;
  #children = new Set();

  validateConfig(config) {
    validateHermesConfig(config);
  }

  async execute(stimulus, options) {
    const job = resolveJob(stimulus, options.executorConfig ?? {});
    const outDir = path.join(options.workDir, OUT_DIR_NAME);
    await mkdir(outDir, { recursive: true });
    const limitMs = options.maxAgentDurationMs ?? options.timeout;
    const startedAt = new Date();

    const args = [DRIVER, "--profile", job.profile, "--fixture", job.fixture, "--task", job.task,
      "--hermes-bin", job.hermesBin, "--out-dir", outDir];
    if (limitMs > 0) args.push("--timeout-seconds", String(limitMs / 1000));
    const child = spawn(job.python, args, {
      cwd: EVALS_WORKSHOP,
      env: mergeEnv(process.env, { ...options.env, PYTHONIOENCODING: "utf-8" }),
      stdio: ["ignore", "ignore", "pipe"],
      detached: process.platform !== "win32",
      windowsHide: true,
    });
    this.#children.add(child);
    options.registerCleanup?.(() => killTree(child));

    let stderr = "";
    child.stderr.on("data", (chunk) => {
      stderr = (stderr + chunk).slice(-2000);
    });
    // The worker's limit is enforced inside tee_hermes.py so PersonaDesk can release its lock.
    // Killing the whole driver is only a backstop if that clean path hangs.
    let killedByBackstop = false;
    const timer = limitMs > 0 ? setTimeout(() => {
      killedByBackstop = true;
      killTree(child);
    }, limitMs + BACKSTOP_GRACE_MS) : undefined;

    const exitCode = await new Promise((resolve, reject) => {
      child.once("error", reject);
      child.once("close", (code) => resolve(code));
    }).catch((err) => {
      throw infraError(`cannot start PersonaDesk driver with '${job.python}': ${err.message}`, false);
    }).finally(() => {
      clearTimeout(timer);
      this.#children.delete(child);
    });
    const completedAt = new Date();
    if (killedByBackstop) {
      throw infraError(`PersonaDesk driver did not stop within ${BACKSTOP_GRACE_MS} ms after the limit; `
        + "check for a stale PersonaDesk lock (personadesk reconcile)", false);
    }
    const timedOut = existsSync(path.join(outDir, "stream.jsonl.timeout"));

    if (exitCode === EXIT_TEMPFAIL) {
      throw infraError(`PersonaDesk lock busy: ${stderr.trim()}`, true);
    }
    if (exitCode === EXIT_CONFIG) {
      throw infraError(`PersonaDesk configuration problem: ${stderr.trim()}`, false);
    }

    const streamText = (await readIfPresent(path.join(outDir, "stream.jsonl"))) ?? "";
    const parts = streamToTrajectoryParts(streamText);
    const events = parts.events;
    const jobText = await readIfPresent(path.join(outDir, "job.json"));
    const jobRecord = jobText ? JSON.parse(jobText) : undefined;
    if (jobRecord?.job) {
      events.push({
        type: "custom",
        turn: 0,
        data: {
          kind: "personadesk_job",
          status: jobRecord.job.status,
          job_id: jobRecord.job.job_id,
          error: jobRecord.job.error ?? null,
          artifact_hash: jobRecord.draft?.artifact_hash ?? null,
          malformed_lines: parts.malformedLines,
        },
      });
      if (jobRecord.job.status === "failed" && !events.some((e) => e.type === "error")) {
        events.push({ type: "error", turn: 0, data: { message: `PersonaDesk job failed: ${jobRecord.job.error}`, type: "personadesk_job" } });
      }
    }
    if (timedOut) {
      events.push({ type: "error", turn: 0, data: { message: `stopped at the ${limitMs} ms limit`, type: "timeout" } });
    }

    const artifactsDir = options.sessionLog?.executorArtifactsDir;
    if (artifactsDir && streamText) {
      await mkdir(artifactsDir, { recursive: true });
      await copyFile(path.join(outDir, "stream.jsonl"), path.join(artifactsDir, "hermes-stream.jsonl"));
    }

    const metrics = computeMetrics(events);
    metrics.wallTimeMs = completedAt.getTime() - startedAt.getTime();
    const sessionID = parts.sessionId ?? options.sessionID ?? `hermes-${startedAt.getTime()}`;
    return {
      id: sessionID,
      stimulus,
      events,
      metrics,
      output: parts.output,
      workDir: options.workDir,
      endReason: timedOut ? "agent_timeout" : "completed",
      metadata: {
        model: parts.model ?? options.model ?? "unknown",
        skillsLoaded: [],
        startedAt,
        completedAt,
        executor: this.name,
        sessionID,
      },
    };
  }

  async shutdown() {
    for (const child of this.#children) killTree(child);
    this.#children.clear();
  }
}
