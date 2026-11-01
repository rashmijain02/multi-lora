// Runs the workshop-pinned Vally CLI with telemetry OFF.
// Vally 0.20.0 sends usage telemetry to Azure Application Insights by default; this
// workshop never sends data off the machine without an explicit choice. If you do want to
// share telemetry, call node_modules/.bin/vally directly instead of this wrapper.
//   npm run vally -- lint --eval-spec evals/10-priya/eval.yaml
import { spawnSync } from "node:child_process";
import { createRequire } from "node:module";
import path from "node:path";

const require = createRequire(import.meta.url);
const cliPkg = require.resolve("@microsoft/vally-cli/package.json");
const cli = path.join(path.dirname(cliPkg), "dist", "index.js");

const env = { ...process.env };
env.VALLY_TELEMETRY_OPTOUT = "1";

const r = spawnSync(process.execPath, [cli, ...process.argv.slice(2)], { stdio: "inherit", env });
process.exit(r.status ?? 1);
