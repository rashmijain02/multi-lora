// Unit tests for the pure stream -> trajectory mapping. Streams under streams/ were recorded
// from scripts/fake_hermes.py (fake-*.jsonl) or hand-written in Hermes's documented shape
// (hermes-shape.jsonl: tool_call_id, text deltas, token counts).
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import { computeMetrics } from "@microsoft/vally";
import { streamToTrajectoryParts } from "../src/stream-to-trajectory.js";

const stream = (name) => readFileSync(new URL(`./streams/${name}.jsonl`, import.meta.url), "utf8");
const ofType = (events, type) => events.filter((e) => e.type === type);

test("fake ok run maps every tool call, pairs results, and ends the turn", () => {
  const p = streamToTrajectoryParts(stream("fake-ok"));
  const calls = ofType(p.events, "tool_call");
  assert.deepEqual(calls.map((e) => e.data.toolName),
    ["pd_read_fixture", "pd_run_check", "pd_run_check", "pd_draft_reply"]);
  const results = ofType(p.events, "tool_result");
  assert.deepEqual(results.map((e) => e.data.toolCallId), calls.map((e) => e.data.toolCallId));
  assert.ok(results.every((e) => e.data.success));
  assert.equal(p.output, "Draft stored (4 tool calls).");
  assert.equal(p.model, "fake-controller");
  assert.equal(ofType(p.events, "error").length, 0);
  assert.equal(p.events.at(-1).type, "turn_end");
  assert.equal(p.events[0].type, "turn_start");
  const metrics = computeMetrics(p.events);
  assert.equal(metrics.toolCallCount, 4);
  assert.equal(metrics.toolCallBreakdown.pd_run_check, 2);
});

test("tool results are parsed JSON so graders can match on fields", () => {
  const p = streamToTrajectoryParts(stream("fake-ok"));
  const draft = ofType(p.events, "tool_result").find((e) => e.data.toolName === "pd_draft_reply");
  assert.equal(draft.data.result.ok, true);
  assert.match(draft.data.result.body, /billing team/);
});

test("a result with an error becomes an error event but still ends the turn", () => {
  const p = streamToTrajectoryParts(stream("fake-error"));
  assert.equal(ofType(p.events, "error").length, 1);
  assert.equal(ofType(p.events, "turn_end").length, 1);
});

test("a nonzero exit_code becomes an error event", () => {
  const p = streamToTrajectoryParts(stream("fake-nonzero"));
  const [err] = ofType(p.events, "error");
  assert.match(err.data.message, /exit_code 1/);
});

test("malformed lines are counted, not fatal, and a missing result never ends the turn", () => {
  const p = streamToTrajectoryParts(stream("fake-malformed"));
  assert.equal(p.malformedLines, 1);
  assert.equal(ofType(p.events, "turn_end").length, 0);
  assert.equal(ofType(p.events, "error")[0].data.type, "no_result");
});

test("a stream without a result has no turn_end, so `completed` cannot pass", () => {
  const p = streamToTrajectoryParts(stream("fake-no_result"));
  assert.ok(ofType(p.events, "tool_call").length > 0);
  assert.equal(ofType(p.events, "turn_end").length, 0);
});

test("Hermes-shaped stream: ids, text deltas, tool errors and tokens", () => {
  const p = streamToTrajectoryParts(stream("hermes-shape"));
  assert.deepEqual(ofType(p.events, "tool_call").map((e) => e.data.toolCallId), ["call_a", "call_b"]);
  const denied = ofType(p.events, "tool_result")[1];
  assert.equal(denied.data.success, false);
  assert.match(denied.data.error.message, /permission_denied/);
  assert.equal(ofType(p.events, "assistant_message")[0].data.content,
    "Draft stored; refund routed to billing.");
  assert.equal(p.output, "Draft stored; refund routed to billing.");
  const [usage] = ofType(p.events, "token_usage");
  assert.deepEqual(usage.data, { inputTokens: 1200, outputTokens: 85, cacheReadTokens: 400,
    cacheWriteTokens: 0, model: "example-hosted-model" });
  assert.equal(p.sessionId, "sess-example-1");
  assert.ok(p.events[1].timestamp instanceof Date);
});

test("empty input yields only a no_result error", () => {
  const p = streamToTrajectoryParts("");
  assert.deepEqual(p.events.map((e) => e.type), ["error"]);
  assert.equal(p.output, "");
});
