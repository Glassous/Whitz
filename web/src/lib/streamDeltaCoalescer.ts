/**
 * Frame-paced coalescer for high-frequency SSE / IPC streaming deltas.
 *
 * Batches incoming deltas into a lightweight accumulator and flushes them on a fixed
 * cadence (default 32ms ≈ 30 Hz) to avoid flooding Vue reactivity and Markdown DOM updates.
 * Call `flushNow()` synchronously before any structural/terminal event to preserve strict ordering.
 */
export interface DeltaCoalescer<TChunk> {
  push(chunk: TChunk): void;
  flushNow(): void;
  clear(): void;
  hasPending(): boolean;
}

export function createDeltaCoalescer<TChunk, TBatch>(options: {
  intervalMs?: number;
  createEmpty: () => TBatch;
  append: (batch: TBatch, chunk: TChunk) => void;
  isEmpty: (batch: TBatch) => boolean;
  onFlush: (batch: TBatch) => void;
}): DeltaCoalescer<TChunk> {
  const intervalMs = options.intervalMs ?? 32;
  let pending: TBatch = options.createEmpty();
  let timer: ReturnType<typeof setTimeout> | null = null;

  function drain(): TBatch | null {
    if (timer !== null) {
      clearTimeout(timer);
      timer = null;
    }
    if (options.isEmpty(pending)) return null;
    const batch = pending;
    pending = options.createEmpty();
    return batch;
  }

  function schedule() {
    if (timer !== null) return;
    timer = setTimeout(() => {
      timer = null;
      const batch = drain();
      if (batch) options.onFlush(batch);
    }, intervalMs);
  }

  return {
    push(chunk: TChunk) {
      options.append(pending, chunk);
      if (!options.isEmpty(pending)) {
        schedule();
      }
    },
    flushNow() {
      const batch = drain();
      if (batch) options.onFlush(batch);
    },
    clear() {
      if (timer !== null) {
        clearTimeout(timer);
        timer = null;
      }
      pending = options.createEmpty();
    },
    hasPending() {
      return !options.isEmpty(pending);
    },
  };
}
