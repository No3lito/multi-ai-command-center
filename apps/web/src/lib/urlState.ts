/**
 * The dashboard is a single static page. The selected room lives in the
 * `?room=<room_id>` query parameter so the backend only has to serve
 * out/index.html at `/` (query strings never change the file served).
 */

const ROOM_ID = /^room_[A-Za-z0-9_-]{1,64}$/;

export function readRoomParam(search: string = window.location.search): string | null {
  const value = new URLSearchParams(search).get("room");
  return value && ROOM_ID.test(value) ? value : null;
}

export function writeRoomParam(roomId: string, mode: "push" | "replace"): void {
  const url = new URL(window.location.href);
  if (url.searchParams.get("room") === roomId) return;
  url.searchParams.set("room", roomId);
  const next = `${url.pathname}${url.search}${url.hash}`;
  if (mode === "push") window.history.pushState(null, "", next);
  else window.history.replaceState(null, "", next);
}
