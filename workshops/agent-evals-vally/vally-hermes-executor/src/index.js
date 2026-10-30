// Vally loads this with `vally eval --executor-plugin ./vally-hermes-executor`.
import { HermesExecutor } from "./hermes-executor.js";

export function registerExecutors(registry) {
  registry.register(new HermesExecutor());
}

export { HermesExecutor };
