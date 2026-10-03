# Adding commands from your own mod

Your RE_Kenshi plugin can add commands to the harness inbox and hook harness
actions. There's no link-time dependency: copy
`include/KenshiAutomationHarness.h` into your project; `KAH_Connect()` finds
`AutomationHarness.dll` at run time and returns 0 when it isn't installed,
so your mod works the same for players without the harness.

```cpp
#include "KenshiAutomationHarness.h"

static int CmdMyState(const char *id, int argc, const char *const *argv,
                      KAH_Reply *reply, void *user) {
  if (argc < 2) {
    reply->append(reply, "usage: mystate <npc>");
    return 0; // error
  }
  // ... look the character up, build the text ...
  reply->append(reply, "{\"ok\":true}");
  return 1; // ok
}

static void BeforeAttack(void *attacker, void *target, void *user) {
  // e.g. lift your mod's truce between the two factions so the order sticks
}

static bool g_kahConnected = false;

static void ConnectHarness() { // call from startPlugin, and again later if it failed
  if (g_kahConnected)
    return;
  KAH_Api kah;
  if (!KAH_Connect(&kah))
    return;
  kah.registerCommand("mystate", "mystate <npc>", &CmdMyState, nullptr);
  kah.registerBeforeAttack(&BeforeAttack, nullptr);
  kah.log("MyMod: harness commands registered");
  g_kahConnected = true;
}
```

Rules:
- **Load order:** plugins load in mod-list order. If your plugin loads before
  the harness, `KAH_Connect()` returns 0 in your `startPlugin`; call it again
  on your first game-thread update.
- **Names:** letters, digits, `_`, `-`, `.`; up to 64 characters; matched
  case-insensitively. Built-in names and names another mod already took are
  refused (`registerCommand` returns 0). Prefix yours (`mymod_state`) to avoid
  clashes.
- **Threading:** handlers run on the game thread, from the frame listener, at
  the main menu too: check a game is loaded before touching the world.
- **Arguments:** `argv[0]` is the command name, `argv[1..argc-1]` its
  arguments; `id` is the request id (for your own logging). Strings are valid
  only during the call.
- **Reply:** call `reply->append` as often as you like; tabs and newlines
  become spaces. Return 1 for `ok`, 0 for `error`.
- **Exceptions** in handlers are caught and reported as errors, but don't rely
  on it: a crash in your handler is a crash in the game.
- `registerBeforeAttack` hooks run, in registration order, just before the
  built-in `attack` command gives its order.
