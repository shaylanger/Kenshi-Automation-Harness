// Offline regression for the `newgame` chargen latch (src/NewGameEditorState.h).
#include "NewGameEditorState.h"

#include <cstdio>

int g_failed = 0;
void Check(bool cond, const char *what) {
  printf("%s %s\n", cond ? "PASS" : "FAIL", what);
  if (!cond)
    ++g_failed;
}

int main() {
  NewGameEditorState state;
  Check(!state.IsOpen(false, false, false, true, 0), "no pending newgame ignores a GUI probe");
  Check(!state.IsOpen(true, false, false, false, 10), "loading waits until the editor is observed");
  Check(state.IsOpen(true, false, false, true, 20), "first GUI observation latches the editor open");
  Check(state.observedOpen, "editor-open observation is retained");
  Check(state.IsOpen(true, false, false, false, 30), "chargen stays open without repeating the GUI probe");
  Check(state.IsOpen(true, false, true, false, 40), "player flag baseline is recorded before auto-confirm");
  Check(state.IsOpen(true, false, false, false, 50), "pre-confirm false does not close auto-confirm chargen");
  Check(state.IsOpen(true, true, false, false, 100), "first transient false after the confirm action does not close chargen");
  Check(state.IsOpen(true, true, true, false, 200), "a true flag resets the false-reading window");
  Check(state.IsOpen(true, true, false, false, 300), "closure needs a stable false window");
  Check(state.IsOpen(true, true, false, false, 1299), "false for less than one second is transient");
  Check(!state.IsOpen(true, true, false, false, 1300), "one second of false after a seen true confirms closure");

  state.Reset();
  Check(state.IsOpen(true, false, true, true, 2000), "a second newgame can observe its own editor and flag");
  Check(state.IsOpen(true, true, true, false, 2100), "second editor enters closure watch");
  Check(state.IsOpen(true, true, true, false, 8000), "step-2 retry timeout preserves closure monitoring");
  Check(state.IsOpen(true, true, false, false, 8100), "delayed close starts its stable-false window after timeout");
  Check(!state.IsOpen(true, true, false, false, 9100), "delayed closure is detected after the retry timeout");

  state.Reset();
  Check(!state.observedOpen && !state.IsOpen(true, false, false, false, 10000), "reset permits a fresh transition probe");
  Check(state.IsOpen(true, false, false, true, 10010), "fresh probe latches after reset");

  state.Reset();
  Check(state.IsOpen(true, false, false, true, 11000), "editor latches even when its player flag is absent");
  Check(state.IsOpen(true, true, false, false, 12000), "an absent player flag fails safe and keeps chargen pending");
  Check(state.IsOpen(true, true, false, false, 15000), "an absent flag never falsely claims editor closure");

  state.Reset();
  Check(state.IsOpen(true, true, true, true, 20000), "edit mode establishes a player-flag baseline");
  Check(state.IsOpen(true, true, false, false, 20010), "edit mode tolerates a transient false flag");
  Check(!state.IsOpen(true, true, false, false, 21010), "manual edit confirmation is detected without KAH confirm steps");

  state.Reset();
  Check(state.IsOpen(true, false, true, true, 30000), "auto-confirm fallback baseline is captured");
  Check(state.IsOpen(true, false, false, false, 30010), "fallback remains unarmed before its bounded retry limit");
  Check(state.IsOpen(true, true, false, false, 30020), "exhausted-probe manual fallback arms closure detection");
  Check(!state.IsOpen(true, true, false, false, 31020), "manual click after exhausted retries clears chargen");
  printf(g_failed ? "newgame_editor_state_test: %d FAILED\n" : "newgame_editor_state_test: all passed\n", g_failed);
  return g_failed ? 1 : 0;
}
