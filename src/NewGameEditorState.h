// Tracks the character-editor transition for KAH `newgame`.
// The game's GUI mode query is only used until the editor has first been seen;
// after that, avoid re-entering GUI mode code while chargen is active.
#pragma once

struct NewGameEditorState {
  bool observedOpen;
  bool playerFlagSeenOpen;
  unsigned long playerFlagFalseSince;

  NewGameEditorState() : observedOpen(false), playerFlagSeenOpen(false), playerFlagFalseSince(0) {}

  void Reset() {
    observedOpen = false;
    playerFlagSeenOpen = false;
    playerFlagFalseSince = 0;
  }

  bool IsOpen(bool pending, bool closureWatchArmed, bool playerEditorFlag, bool guiProbe, unsigned long now) {
    if (!pending)
      return false;
    if (!observedOpen) {
      if (guiProbe) {
        observedOpen = true;
        if (playerEditorFlag)
          playerFlagSeenOpen = true;
      }
      return guiProbe;
    }
    if (playerEditorFlag)
      playerFlagSeenOpen = true;
    if (playerEditorFlag) {
      playerFlagFalseSince = 0;
      return true;
    }
    // Establish the player flag baseline independently of KAH's auto-confirm
    // step so `edit` and the exhausted-probe/manual-click path can finish too.
    // When auto-confirm is active, wait until KAH has acted before treating a
    // stable clear as completion. An absent flag always fails safe.
    if (!closureWatchArmed || !playerFlagSeenOpen)
      return true;
    if (playerFlagFalseSince == 0)
      playerFlagFalseSince = now;
    // Require a full second of stable false readings to tolerate the
    // transient false values seen while the editor is closing.
    return now - playerFlagFalseSince < 1000;
  }
};
