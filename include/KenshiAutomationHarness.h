/* Kenshi Automation Harness: extension API for other RE_Kenshi plugins.
 *
 * A mod can add its own test commands to the harness inbox and react to
 * harness actions, without linking against the harness: include this header
 * and call KAH_Connect(). It finds AutomationHarness.dll at run time and
 * returns 0 when the harness isn't installed, so a mod works the same
 * without it.
 *
 * Plugins load in mod-list order, so the harness may not be loaded yet when
 * your startPlugin() runs: if KAH_Connect() returns 0 there, call it again
 * later (e.g. on your first game-thread update) before giving up.
 *
 * Handlers run on the game thread, from the harness frame listener, at the
 * main menu too (check that a game is loaded if your command needs one).
 * Plain C across the DLL boundary: strings are UTF-8/ANSI char*, valid only
 * for the duration of the call.
 */
#ifndef KENSHI_AUTOMATION_HARNESS_H
#define KENSHI_AUTOMATION_HARNESS_H

#include <windows.h>

#ifdef __cplusplus
extern "C" {
#endif

#define KAH_API_VERSION 1
#define KAH_DLL_NAME "AutomationHarness.dll"

/* Reply text for the outbox line ("id<TAB>ok|error<TAB>text"). Call
 * reply->append(reply, text) any number of times; tabs and newlines are
 * replaced by spaces. */
typedef struct KAH_Reply {
  void *impl;
  void (*append)(struct KAH_Reply *reply, const char *text);
} KAH_Reply;

#define KAH_ERROR 0
#define KAH_OK 1
/* The handler will answer later with complete() (the reply text is ignored). */
#define KAH_PENDING 2

/* A registered command. id = the request id from the inbox line,
 * argv[0] = the command name, argv[1..argc-1] = its arguments.
 * Return KAH_OK, KAH_ERROR, or KAH_PENDING to answer later (e.g. from your
 * own game-thread hook) with api.complete(id, ok, text). */
typedef int (*KAH_CommandFn)(const char *id, int argc, const char *const *argv,
                             KAH_Reply *reply, void *user);

/* Called by the "attack" command just before the attack order is given
 * (attacker and target are Character*). Use it to lift a mod-side truce or
 * protection so the order sticks. */
typedef void (*KAH_AttackFn)(void *attacker, void *target, void *user);

/* Exported by AutomationHarness.dll. */
typedef int (*KAH_ApiVersionFn)(void);
typedef int (*KAH_RegisterCommandFn)(const char *name, const char *usage,
                                     KAH_CommandFn fn, void *user);
typedef int (*KAH_RegisterBeforeAttackFn)(KAH_AttackFn fn, void *user);
typedef void (*KAH_LogFn)(const char *message);
typedef void (*KAH_CompleteFn)(const char *id, int ok, const char *text);
/* Character lookup with the harness's own <npc> forms (name, #serial/index,
 * #serial, @player, @selected); game thread only. Returns a Character* or
 * NULL with the reason in error (errorSize bytes, may be 0). */
typedef void *(*KAH_FindCharacterFn)(const char *ref, char *error, int errorSize);
/* 1 while the harness input isolation is on (input_isolation on): the game
 * window is treated as focused and real input is replaced by injected input
 * (key_inject / mouse_inject; GetAsyncKeyState and DirectInput already return
 * it). A mod that gates input on window focus should treat 1 as focused. */
typedef int (*KAH_InputIsolatedFn)(void);

typedef struct KAH_Api {
  int version;
  /* 1 = registered; 0 = name taken by a built-in or another mod, or bad args. */
  KAH_RegisterCommandFn registerCommand;
  KAH_RegisterBeforeAttackFn registerBeforeAttack;
  /* Writes one line to the harness log (harness.log). */
  KAH_LogFn log;
  /* Answers a command whose handler returned KAH_PENDING (any thread). */
  KAH_CompleteFn complete;
  /* Optional: NULL with a harness older than 2026-10-03 (check before use). */
  KAH_FindCharacterFn findCharacter;
  /* Optional: NULL with a harness older than 2026-10-07 (check before use). */
  KAH_InputIsolatedFn inputIsolated;
} KAH_Api;

/* Fills *api and returns 1 when the harness is loaded, else returns 0. */
static int KAH_Connect(KAH_Api *api) {
  HMODULE dll;
  KAH_ApiVersionFn version;
  if (!api)
    return 0;
  ZeroMemory(api, sizeof(*api));
  dll = GetModuleHandleA(KAH_DLL_NAME);
  if (!dll)
    return 0;
  version = (KAH_ApiVersionFn)GetProcAddress(dll, "KAH_ApiVersion");
  if (!version || version() < KAH_API_VERSION)
    return 0;
  api->version = version();
  api->registerCommand = (KAH_RegisterCommandFn)GetProcAddress(dll, "KAH_RegisterCommand");
  api->registerBeforeAttack =
      (KAH_RegisterBeforeAttackFn)GetProcAddress(dll, "KAH_RegisterBeforeAttack");
  api->log = (KAH_LogFn)GetProcAddress(dll, "KAH_Log");
  api->complete = (KAH_CompleteFn)GetProcAddress(dll, "KAH_Complete");
  api->findCharacter = (KAH_FindCharacterFn)GetProcAddress(dll, "KAH_FindCharacter");
  api->inputIsolated = (KAH_InputIsolatedFn)GetProcAddress(dll, "KAH_InputIsolated");
  return api->registerCommand && api->registerBeforeAttack && api->log && api->complete ? 1
                                                                                         : 0;
}

#ifdef __cplusplus
}
#endif

#endif /* KENSHI_AUTOMATION_HARNESS_H */
