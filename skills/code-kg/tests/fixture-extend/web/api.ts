// Client for the controller's status endpoint.
export async function fetchStatus(): Promise<Record<string, number>> {
  // TODO: retry once on a network error
  const res = await fetch("/status");
  return res.json();
}
