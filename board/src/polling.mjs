// A single flight at a time. Stopping also cancels an in-flight network request.
export function startPolling(
  tick,
  {
    interval = 1800,
    onError = () => {},
    schedule = setTimeout,
    cancel = clearTimeout,
  } = {},
) {
  const controller = new AbortController();
  let timer;
  async function run() {
    try {
      await tick(controller.signal);
    } catch (error) {
      if (!controller.signal.aborted) onError(error);
    } finally {
      if (!controller.signal.aborted) timer = schedule(run, interval);
    }
  }
  void run();
  return () => {
    controller.abort();
    cancel(timer);
  };
}

export function debounce(
  callback,
  delay,
  schedule = setTimeout,
  cancel = clearTimeout,
) {
  let timer;
  const run = (...args) => {
    cancel(timer);
    timer = schedule(() => callback(...args), delay);
  };
  run.cancel = () => cancel(timer);
  return run;
}
