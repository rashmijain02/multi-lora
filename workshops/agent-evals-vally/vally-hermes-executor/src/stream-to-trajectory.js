// Pure mapping from Hermes `stream-json` lines to Vally trajectory events.
// No I/O here, so every rule can be unit-tested with recorded streams.
//
// Hermes protocol (external/hermes-agent/hermes_cli/stream_json.py):
//   {"type":"system","subtype":"init","model","session_id"}
//   {"type":"text","text"}                       assistant text delta
//   {"type":"tool_use","name","tool_call_id"?,"input"?}
//   {"type":"tool_result","name","tool_call_id"?,"output","duration_ms","is_error"}
//   {"type":"result","session_id","exit_code","text","tokens"?,"duration_ms"?,"error"?}
// Every line also carries "timestamp" (ms since epoch).

const TURN_ID = "0";

function toDate(ms) {
  return typeof ms === "number" && Number.isFinite(ms) ? new Date(ms) : undefined;
}

function parseToolOutput(output) {
  if (typeof output !== "string") return output;
  try {
    return JSON.parse(output);
  } catch {
    return output; // truncated or plain-text output stays a string
  }
}

/**
 * @param {string} text raw JSONL from the Hermes worker
 * @returns {{events: object[], output: string, model: string|undefined,
 *            sessionId: string|undefined, result: object|undefined, malformedLines: number}}
 */
export function streamToTrajectoryParts(text) {
  const events = [];
  const pendingIds = new Map(); // tool name -> FIFO of ids, for streams without tool_call_id
  let model;
  let sessionId;
  let result;
  let malformedLines = 0;
  let generatedIds = 0;
  let assistantText = "";
  let started = false;

  const start = (timestamp) => {
    if (!started) {
      events.push({ type: "turn_start", timestamp, turn: 0, data: { turnId: TURN_ID } });
      started = true;
    }
  };

  for (const raw of text.split(/\r?\n/)) {
    const line = raw.trim();
    if (!line) continue;
    let event;
    try {
      event = JSON.parse(line);
    } catch {
      malformedLines += 1;
      continue;
    }
    if (event === null || typeof event !== "object" || Array.isArray(event)) {
      malformedLines += 1;
      continue;
    }
    const timestamp = toDate(event.timestamp);
    switch (event.type) {
      case "system":
        model = event.model ?? model;
        sessionId = event.session_id ?? sessionId;
        start(timestamp);
        break;
      case "text":
        start(timestamp);
        assistantText += String(event.text ?? "");
        break;
      case "tool_use": {
        start(timestamp);
        const toolName = String(event.name ?? "unknown");
        let toolCallId = event.tool_call_id;
        if (!toolCallId) {
          generatedIds += 1;
          toolCallId = `${toolName}-${generatedIds}`;
          const queue = pendingIds.get(toolName) ?? [];
          queue.push(toolCallId);
          pendingIds.set(toolName, queue);
        }
        const data = { toolName, toolCallId, turnId: TURN_ID };
        if (event.input !== undefined) data.arguments = event.input;
        events.push({ type: "tool_call", timestamp, turn: 0, data });
        break;
      }
      case "tool_result": {
        start(timestamp);
        const toolName = String(event.name ?? "unknown");
        const toolCallId = event.tool_call_id ?? pendingIds.get(toolName)?.shift() ?? `${toolName}-orphan`;
        const success = event.is_error !== true;
        const data = { toolName, toolCallId, success, result: parseToolOutput(event.output) };
        if (!success) data.error = { message: String(event.output ?? "tool error").slice(0, 500) };
        events.push({ type: "tool_result", timestamp, turn: 0, data });
        break;
      }
      case "result":
        result = event;
        sessionId = event.session_id ?? sessionId;
        break;
      default:
        break; // unknown event types are ignored, not fatal
    }
  }

  const output = (result && typeof result.text === "string" && result.text) || assistantText;
  if (assistantText || output) {
    events.push({ type: "assistant_message", turn: 0, data: { content: assistantText || output } });
  }
  if (result?.tokens) {
    const t = result.tokens;
    events.push({
      type: "token_usage",
      timestamp: toDate(result.timestamp),
      turn: 0,
      data: {
        inputTokens: Number(t.input ?? 0),
        outputTokens: Number(t.output ?? 0),
        cacheReadTokens: Number(t.cache_read ?? 0),
        cacheWriteTokens: Number(t.cache_write ?? 0),
        model: model ?? "unknown",
      },
    });
  }
  if (!result) {
    events.push({ type: "error", turn: 0, data: { message: "Hermes stream ended without a result event", type: "no_result" } });
  } else if (result.error || result.exit_code !== 0) {
    events.push({
      type: "error",
      timestamp: toDate(result.timestamp),
      turn: 0,
      data: { message: String(result.error ?? `Hermes exit_code ${result.exit_code}`), type: "hermes_result" },
    });
  }
  if (result) {
    // A turn only "ends" when Hermes reports a terminal result; Vally's `completed` grader
    // requires a turn_end, so a killed or truncated run can never pass it.
    events.push({ type: "turn_end", timestamp: toDate(result.timestamp), turn: 0, data: { turnId: TURN_ID } });
  }
  return { events, output, model, sessionId, result, malformedLines };
}
