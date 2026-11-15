import { fetchStatus } from "./api";

/* HACK: polls on a timer until the controller exposes events */
export async function render(root: HTMLElement): Promise<void> {
  const status = await fetchStatus();
  root.textContent = JSON.stringify(status);
}
