export type ScientificViewerKind = "preview" | "volume" | "mesh";
export type TheatreState = { active: ScientificViewerKind | null; drawerCollapsed: boolean };
export type TheatreEvent =
  | { type: "toggle"; viewer: ScientificViewerKind }
  | { type: "drawer" }
  | { type: "exit" };

export const INITIAL_THEATRE_STATE: TheatreState = Object.freeze({
  active: null,
  drawerCollapsed: false
});

export function reduceTheatreState(state: TheatreState, event: TheatreEvent): TheatreState {
  if (event.type === "exit") return { ...INITIAL_THEATRE_STATE };
  if (event.type === "drawer") {
    return state.active ? { ...state, drawerCollapsed: !state.drawerCollapsed } : state;
  }
  if (state.active === event.viewer) return { ...INITIAL_THEATRE_STATE };
  return { active: event.viewer, drawerCollapsed: false };
}

export function shouldExitTheatre(key: string): boolean {
  return key === "Escape" || key === "Esc";
}

export function theatreViewportBox(
  viewportWidth: number,
  viewportHeight: number,
  inset = 8
): { width: number; height: number; inset: number } {
  const safeInset = Math.max(0, Number.isFinite(inset) ? inset : 0);
  return {
    width: Math.max(0, viewportWidth - safeInset * 2),
    height: Math.max(0, viewportHeight - safeInset * 2),
    inset: safeInset
  };
}

export function canUseBrowserFullscreen(documentLike: {
  fullscreenEnabled?: boolean;
  documentElement?: { requestFullscreen?: unknown };
}): boolean {
  return Boolean(
    documentLike.fullscreenEnabled &&
    typeof documentLike.documentElement?.requestFullscreen === "function"
  );
}

