import assert from "node:assert/strict";
import { pathToFileURL } from "node:url";
import path from "node:path";
import { fileURLToPath } from "node:url";
const root = path.dirname(fileURLToPath(import.meta.url));
const m = await import(pathToFileURL(path.join(root, "..", "src", "theatreMode.ts")).href);

let state = m.reduceTheatreState(m.INITIAL_THEATRE_STATE, { type: "toggle", viewer: "preview" });
assert.deepEqual(state, { active: "preview", drawerCollapsed: false });
state = m.reduceTheatreState(state, { type: "drawer" });
assert.equal(state.drawerCollapsed, true);
state = m.reduceTheatreState(state, { type: "toggle", viewer: "volume" });
assert.deepEqual(state, { active: "volume", drawerCollapsed: false });
assert.deepEqual(m.reduceTheatreState(state, { type: "exit" }), m.INITIAL_THEATRE_STATE);
assert.equal(m.shouldExitTheatre("Escape"), true);
assert.equal(m.shouldExitTheatre("Enter"), false);
assert.deepEqual(m.theatreViewportBox(1280, 720, 8), { width: 1264, height: 704, inset: 8 });
assert.deepEqual(m.theatreViewportBox(320, 200, 500), { width: 0, height: 0, inset: 500 });
assert.equal(m.canUseBrowserFullscreen({ fullscreenEnabled: false }), false);
assert.equal(m.canUseBrowserFullscreen({ fullscreenEnabled: true, documentElement: { requestFullscreen() {} } }), true);
console.log("theatreMode.test.mjs: all passed");

