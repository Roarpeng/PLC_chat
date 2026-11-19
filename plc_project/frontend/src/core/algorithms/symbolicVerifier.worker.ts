import type {
  GhostGraphTransaction,
  StationHyperGraph,
  VerificationReport,
} from '../ir/afHyperGraph.types';
import { verifyStationHyperGraph } from './symbolicVerifier';

export interface SymbolicVerifierWorkerInput {
  station: StationHyperGraph;
  ghostTx?: GhostGraphTransaction | null;
}

/**
 * 纯函数消息处理入口：接收 `{ station, ghostTx }` 并返回 `VerificationReport`。
 */
export function handleVerifierWorkerMessage(
  payload: SymbolicVerifierWorkerInput
): VerificationReport {
  return verifyStationHyperGraph(payload.station, payload.ghostTx ?? null);
}

interface WorkerGlobalScopeLike {
  onmessage: ((event: MessageEvent<SymbolicVerifierWorkerInput>) => void) | null;
  postMessage?: (message: VerificationReport) => void;
}

const workerScope = globalThis as unknown as WorkerGlobalScopeLike;

if (typeof window === 'undefined' && typeof workerScope.postMessage === 'function') {
  workerScope.onmessage = (event: MessageEvent<SymbolicVerifierWorkerInput>) => {
    const report = handleVerifierWorkerMessage(event.data);
    workerScope.postMessage?.(report);
  };
}
