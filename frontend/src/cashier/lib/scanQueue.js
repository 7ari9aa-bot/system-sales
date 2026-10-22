/**
 * A barcode scanner types the next code before the previous lookup has answered. Two rules keep every code:
 * lookups run strictly one after another, and the input is cleared only if it still holds the code that was just
 * handled (otherwise the previous lookup finishing would erase the code typed after it).
 */
export function createScanQueue() {
  let tail = Promise.resolve();
  return {
    /** Runs `task` after every earlier task has finished; a failing task never blocks the next. */
    push(task) {
      tail = tail.then(task).catch(() => {});
      return tail;
    },
  };
}

/** The value the input should hold after `handled` was processed: emptied only if nothing newer was typed. */
export function clearedIfStill(current, handled) {
  return String(current).trim() === String(handled).trim() ? "" : current;
}
