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
    return KAH_ERROR;
  }
  // ... look the character up, build the text ...
  reply->append(reply, "{\"ok\":true}");
  return KAH_OK;
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
  arguments; `id` is the request id. Strings are valid
  only during the call.
- **Reply:** call `reply->append` as often as you like; tabs and newlines
  become spaces. Return `KAH_OK`, `KAH_ERROR`, or `KAH_PENDING` (below).
- **Exceptions** in handlers are caught and reported as errors, but don't rely
  on it: a crash in your handler is a crash in the game.
- `registerBeforeAttack` hooks run, in registration order, just before the
  built-in `attack` command gives its order.

## Answering later (KAH_PENDING)

Handlers run from the harness frame listener. If your command has to run
somewhere else (inside one of your own game hooks, say, or after something
finishes), queue it and return `KAH_PENDING`; answer later, from any thread,
with `api.complete(id, KAH_OK or KAH_ERROR, text)`. Until then the client sees
no reply (its timeout applies). Copy `id`: it's only valid during the call.

```cpp
static KAH_Api g_kah;
static std::vector<std::vector<std::string> > g_queue; // guard with your own lock

static int CmdMyAction(const char *id, int argc, const char *const *argv,
                       KAH_Reply *reply, void *user) {
  std::vector<std::string> request(argv, argv + argc);
  request.insert(request.begin(), id);
  g_queue.push_back(request);
  return KAH_PENDING;
}

// in your own game-thread hook:
//   for each queued request: run it, then
//   g_kah.complete(request[0].c_str(), ok ? KAH_OK : KAH_ERROR, text.c_str());
```

To take the same `<npc>` forms as the built-ins (name, `#serial/index`, `#serial`,
`@player`, `@selected`), call `api.findCharacter(ref, error, sizeof error)` from your
handler (game thread): it returns the `Character*` or NULL with the reason in `error`.
It is NULL with a harness older than 2026-10-03, so check it before use.

If your mod reads input only while the game window has the focus, also accept
`api.inputIsolated && api.inputIsolated()` (1 while `input_isolation on`): automated
runs then keep the game in the background and feed it injected input
(`key_inject` / `mouse_inject`); `GetAsyncKeyState`, `GetKeyState`, `GetCursorPos`
and DirectInput keyboard/mouse reads already return that injected input in-process.
NULL with a harness older than 2026-10-07.

A pending command never completed just times out on the client side; a
`complete` for an unknown or already answered id is ignored (and logged).

## Testing

`tests\run_tests.bat` builds and runs an offline test of the registry and
reply handling (no game needed).
