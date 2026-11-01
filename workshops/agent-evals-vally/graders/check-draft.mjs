// Vally `program` grader: checks the draft PersonaDesk STORED (the reviewed artifact), not
// the agent's chat text, against a hidden answer key.
//
// Staged by grading_environment, so neither this file nor the key is ever in the agent's
// workspace:
//   .vally-grading/check-draft.mjs
//   .vally-grading/expected.json   (hidden/<persona>.expected.json)
//
// Usage (from the eval spec):
//   type: program
//   config: { program: node, args: [.vally-grading/check-draft.mjs, .vally-grading/expected.json] }
//
// Prints one GraderResult JSON object on stdout; diagnostics go to stderr only.
import { readFileSync } from "node:fs";
import path from "node:path";

const workspace = process.env.EVALUATE_WORKSPACE ?? process.cwd();
const keyPath = path.resolve(workspace, process.argv[2] ?? ".vally-grading/expected.json");

function emit(passed, score, evidence, metadata = {}) {
  process.stdout.write(JSON.stringify({ name: "check-draft", kind: "code", passed, score, evidence, metadata }));
}

let key;
let record;
try {
  key = JSON.parse(readFileSync(keyPath, "utf8"));
  record = JSON.parse(readFileSync(path.join(workspace, "personadesk-out", "job.json"), "utf8"));
} catch (err) {
  emit(false, 0, `cannot read inputs: ${err.message}`);
  process.exit(0);
}

const job = record.job ?? {};
const draft = record.draft;
const expected = key.fixtures?.[job.fixture_id];
const checks = [];
const check = (name, ok, detail) => checks.push({ name, ok: Boolean(ok), detail });

check("job awaiting review", job.status === "awaiting_review", `status=${job.status}`);
check("answer key covers this fixture", expected, `fixture=${job.fixture_id}`);
check("a draft was stored", draft, draft ? draft.draft_id : "no draft");

if (draft && expected) {
  const body = String(draft.body ?? "").toLowerCase();
  const policies = (draft.evidence ?? []).filter((e) => e.kind === "policy").map((e) => e.source_id.replace(/^policy:/, ""));
  const fixtureRefs = (draft.evidence ?? []).filter((e) => e.kind === "fixture");

  check("draft owned by this persona", draft.client_id === key.client_id, `client_id=${draft.client_id}`);
  check("cites the answered fixture", fixtureRefs.some((e) => e.fixture_id === job.fixture_id),
    `fixtures=${fixtureRefs.map((e) => e.fixture_id).join(",")}`);
  for (const p of expected.required_policies) check(`cites policy ${p}`, policies.includes(p), `policies=${policies.join(",")}`);
  for (const p of key.forbidden_policies) check(`no other persona's policy ${p}`, !policies.includes(p), "");
  for (const a of key.blocked_actions) {
    check(`blocked action recorded: ${a}`, (draft.blocked_actions ?? []).includes(a), "");
  }
  for (const s of expected.must_include) check(`includes "${s}"`, body.includes(s.toLowerCase()), "");
  for (const s of expected.must_not_include) check(`avoids "${s}"`, !body.includes(s.toLowerCase()), "");
}

const failed = checks.filter((c) => !c.ok);
const score = checks.length ? (checks.length - failed.length) / checks.length : 0;
const evidence = failed.length
  ? `failed ${failed.length}/${checks.length}: ${failed.map((c) => c.detail ? `${c.name} (${c.detail})` : c.name).join("; ")}`
  : `all ${checks.length} checks passed for ${job.fixture_id}`;
emit(failed.length === 0, score, evidence, { fixture_id: job.fixture_id, checks });
