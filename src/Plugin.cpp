// Kenshi Automation Harness (TEST ONLY): drives a running game from scripts.
//
// Active only while <mod folder>\enabled.flag exists. Tooling writes
// inbox.txt (id<TAB>command<TAB>args, one per line); the DLL consumes it on
// the game thread and appends id<TAB>ok|error<TAB>detail lines to
// outbox.txt. Commands run from the Ogre frame listener, so load/status also
// work at the main menu. autoload.txt (one save name) is loaded once the
// main menu is up. While enabled, autosave is off and the game keeps running
// when its window is in the background.
#ifndef NOMINMAX
#define NOMINMAX // OgreRoot.h uses std::min/max
#endif
#include "FrameStats.h"
#include "Harness.h"

#include <core/Functions.h>
#include <kenshi/GameWorld.h>
#include <kenshi/GunClass.h>
#include <kenshi/RootObject.h>
#include <kenshi/Globals.h> // ou
#include <kenshi/Kenshi.h>
#include <kenshi/SaveManager.h>
#include <kenshi/Town.h>
#include <mygui/MyGUI_Delegate.h>
#include <mygui/MyGUI_Gui.h>
#include <ogre/OgreFrameListener.h>
#include <ogre/OgreRenderSystem.h>
#include <ogre/OgreRenderWindow.h>
#include <ogre/OgreRoot.h>

#include <windows.h>
#include <cstdio>
#include <fstream>
#include <sstream>

namespace {

CRITICAL_SECTION g_logLock;
CRITICAL_SECTION g_outboxLock;
struct LockInit {
  LockInit() {
    InitializeCriticalSection(&g_logLock);
    InitializeCriticalSection(&g_outboxLock);
  }
} g_lockInit;

DWORD g_lastPoll = 0;
bool g_loggedFirstTick = false;
bool g_safePointHooked = false;  // Hook_ProcessThreadMessages installed
DWORD g_lastSafePoint = 0;       // GetTickCount of its last call

void PollInbox(GameWorld *world);
void WorldKeepers();

// True while the processThreadMessages safe point fires (loaded world, unpaused).
bool SafePointActive() { return g_safePointHooked && GetTickCount() - g_lastSafePoint < 500; }

} // namespace

const std::string &HarnessDir() {
  static std::string dir;
  if (dir.empty()) {
    HMODULE self = nullptr;
    char path[MAX_PATH] = {0};
    if (GetModuleHandleExA(GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS |
                               GET_MODULE_HANDLE_EX_FLAG_UNCHANGED_REFCOUNT,
                           (LPCSTR)&HarnessDir, &self) &&
        GetModuleFileNameA(self, path, MAX_PATH)) {
      dir = path;
      size_t slash = dir.find_last_of("\\/");
      dir = slash == std::string::npos ? "." : dir.substr(0, slash);
    } else {
      dir = ".";
    }
  }
  return dir;
}

bool FileExists(const std::string &path) {
  return GetFileAttributesA(path.c_str()) != INVALID_FILE_ATTRIBUTES;
}

bool HarnessEnabled() { return FileExists(HarnessDir() + "\\enabled.flag"); }

void Log(const std::string &msg) {
  SYSTEMTIME t;
  GetLocalTime(&t);
  char stamp[32];
  sprintf_s(stamp, "[%02d:%02d:%02d.%03d] ", t.wHour, t.wMinute, t.wSecond,
            t.wMilliseconds);
  EnterCriticalSection(&g_logLock);
  std::ofstream out((HarnessDir() + "\\harness.log").c_str(), std::ios::app);
  out << stamp << msg << "\n";
  LeaveCriticalSection(&g_logLock);
}

void WriteOutbox(const std::string &id, bool ok, const std::string &detail) {
  EnterCriticalSection(&g_outboxLock);
  std::ofstream out((HarnessDir() + "\\outbox.txt").c_str(), std::ios::app);
  out << OneLine(id) << "\t" << (ok ? "ok" : "error") << "\t" << OneLine(detail) << "\n";
  LeaveCriticalSection(&g_outboxLock);
}

std::string Lower(const std::string &value) {
  std::string out = value;
  for (size_t i = 0; i < out.size(); ++i)
    out[i] = (char)tolower((unsigned char)out[i]);
  return out;
}

std::string OneLine(const std::string &value) {
  std::string out = value;
  for (size_t i = 0; i < out.size(); ++i)
    if (out[i] == '\r' || out[i] == '\n' || out[i] == '\t')
      out[i] = ' ';
  return out;
}

std::string Num(double v) {
  std::ostringstream s;
  s.setf(std::ios::fixed);
  s.precision(1);
  s << v;
  return s.str();
}

std::string Int(long long v) {
  std::ostringstream s;
  s << v;
  return s.str();
}

namespace {

std::vector<std::string> SplitTabs(const std::string &line) {
  std::vector<std::string> fields;
  size_t start = 0;
  while (true) {
    size_t tab = line.find('\t', start);
    fields.push_back(line.substr(start, tab == std::string::npos ? std::string::npos
                                                                  : tab - start));
    if (tab == std::string::npos)
      break;
    start = tab + 1;
  }
  return fields;
}

void ProcessInbox(GameWorld *world) {
  if (!HarnessEnabled())
    return;
  const std::string dir = HarnessDir();

  const std::string autoload = dir + "\\autoload.txt";
  if (FileExists(autoload) && Phase(world) == "menu") {
    std::string name;
    {
      std::ifstream in(autoload.c_str());
      std::getline(in, name);
    }
    DeleteFileA(autoload.c_str());
    while (!name.empty() && (name[name.size() - 1] == '\r' || name[name.size() - 1] == ' '))
      name.erase(name.size() - 1);
    std::vector<std::string> f;
    f.push_back("autoload");
    f.push_back("load");
    f.push_back(name);
    bool ok = false, pending = false;
    std::string detail;
    try {
      detail = RunCommand(world, f, ok, pending);
    } catch (...) {
      detail = "exception";
    }
    Log("KAH: autoload " + name + ": " + detail);
    WriteOutbox("autoload", ok, detail);
  }

  const std::string inboxPath = dir + "\\inbox.txt";
  // Take the inbox first (rename), then read and delete our copy (KAH 9): a
  // client may write the next inbox.txt the moment the name is free, and
  // read-then-delete could delete that new command unread.
  const std::string takenPath = dir + "\\inbox.txt.reading";
  if (!FileExists(inboxPath))
    return;
  if (!MoveFileExA(inboxPath.c_str(), takenPath.c_str(), MOVEFILE_REPLACE_EXISTING))
    return; // a writer still has it open: next poll
  std::vector<std::string> lines;
  {
    std::ifstream in(takenPath.c_str());
    if (!in)
      return;
    std::string line;
    while (std::getline(in, line)) {
      if (!line.empty() && line[line.size() - 1] == '\r')
        line.erase(line.size() - 1);
      if (!line.empty())
        lines.push_back(line);
    }
  }
  DeleteFileA(takenPath.c_str());
  for (size_t i = 0; i < lines.size(); ++i) {
    std::vector<std::string> fields = SplitTabs(lines[i]);
    bool ok = false, pending = false;
    std::string detail;
    if (fields.size() < 2) {
      detail = "malformed line";
    } else {
      try {
        detail = RunCommand(world, fields, ok, pending);
      } catch (...) {
        detail = "exception";
        pending = false;
      }
    }
    if (pending)
      continue; // the mod answers later through KAH_Complete
    WriteOutbox(fields[0], ok, detail);
    if (!ok)
      Log("KAH: error id=" + fields[0] + " " + detail);
  }
}

// Runs once per frame on the game thread, at the main menu too
// (GameWorld::mainLoop only runs once a game is loaded).
void Tick(const char *source) {
  GameWorld *world = ou;
  if (!g_loggedFirstTick) {
    g_loggedFirstTick = true;
    Log(std::string("KAH: frame listener running (source=") + source +
        " phase=" + Phase(world) + " thread=" + Int(GetCurrentThreadId()) + ")");
  }
  WatchLoads();
  // In a loaded world the commands run at the safe point instead (see
  // Hook_ProcessThreadMessages); the frame listener takes over again when the
  // safe point has not fired for 500 ms (main menu, loading, game paused).
  if (SafePointActive())
    return;
  PollInbox(world);
}

void PollInbox(GameWorld *world) {
  try {
    SamplerTick(world); // before the 250 ms inbox gate: the sampler keeps its own <ms> interval
  } catch (...) {
    Log("KAH: exception in SamplerTick");
  }
  DWORD now = GetTickCount();
  if (now - g_lastPoll < 250)
    return;
  g_lastPoll = now;
  try {
    LoadPending(); // notice the moment the old squad is gone
    ProcessInbox(world);
  } catch (...) {
    Log("KAH: exception in ProcessInbox");
  }
}

// Safe point for world-changing commands. Every frame the game starts its
// GameWorld thread (factions, squads, AI) before Ogre renders the frame and
// joins it in GameWorld::mainLoop_GPUSensitiveStuff (Ogre frameEnded), which
// then calls processThreadMessages. Ogre frameStarted, where Tick runs, sits
// inside that window, so commands ran while the world thread was walking the
// same squads: "unload" (Platoon::deactivate) crashed the world thread in
// Blackboard::countCharacters (exe+0x268A68, Platoon::activePlatoon null) and
// the game hung behind RE_Kenshi's crash handler (5090 batch K, 2026-10-07).
// Right after processThreadMessages the world thread is joined and idle until
// the next frame's beginThread.
typedef void(__fastcall *ProcessThreadMessagesFn)(GameWorld *);
ProcessThreadMessagesFn g_processThreadMessagesOrig = nullptr;

void __fastcall Hook_ProcessThreadMessages(GameWorld *world) {
  g_processThreadMessagesOrig(world);
  g_lastSafePoint = GetTickCount();
  WorldKeepers();
  PollInbox(world);
}

// processThreadMessages is private in the SDK; find it through its call in
// mainLoop_GPUSensitiveStuff: 48 8B CE (mov rcx,rsi) E8 <rel32>, the first
// such call after the thread join (Steam 1.0.65: +0x68), following
// incremental-link thunks. 0 if the bytes differ.
unsigned char *ProcessThreadMessagesAddr(__int64 gpuAddr) {
  const unsigned char *p = (const unsigned char *)gpuAddr;
  if (!p || IsBadReadPtr(p, 0x120))
    return nullptr;
  for (int i = 0x10; i < 0x118; ++i) {
    if (p[i] == 0x48 && p[i + 1] == 0x8B && p[i + 2] == 0xCE && p[i + 3] == 0xE8) {
      unsigned char *q = (unsigned char *)(p + i + 8) + *(const int *)(p + i + 4);
      for (int hops = 0; hops < 4 && !IsBadReadPtr(q, 5) && q[0] == 0xE9; ++hops)
        q = q + 5 + *(const int *)(q + 1);
      return IsBadReadPtr(q, 16) ? nullptr : q;
    }
  }
  return nullptr;
}

// Frame times for "fps", measured here with QueryPerformanceCounter (game
// thread, like the commands that read them).
FrameStats g_frameStats;
LARGE_INTEGER g_lastFrame = {0};
double g_qpcFreq = 0.0;

void MeasureFrame() {
  LARGE_INTEGER now;
  QueryPerformanceCounter(&now);
  if (g_qpcFreq <= 0.0) {
    LARGE_INTEGER freq;
    QueryPerformanceFrequency(&freq);
    g_qpcFreq = (double)freq.QuadPart;
  }
  if (g_lastFrame.QuadPart != 0 && g_qpcFreq > 0.0)
    g_frameStats.Add((double)(now.QuadPart - g_lastFrame.QuadPart) / g_qpcFreq);
  g_lastFrame = now;
}

// Frame cap for automated runs (Shay 2026-10-10: VSync is off for tests, so the
// game rendered flat out while takes record at 30 fps). <mod folder>\framecap.txt
// holds the target fps (written by kenshi-ctl / the 4080 ctl at a test launch,
// deleted for play); absent, empty or 0 = uncapped. Re-read once a second, so it
// can change in a running game. Waits at the start of the Ogre frame with a
// high-resolution waitable timer (Sleep fallback), no busy spin.
int g_capFps = 0;
DWORD g_capReadTick = 0;
LARGE_INTEGER g_capNext = {0};
HANDLE g_capTimer = nullptr;

void ReadFrameCap() {
  int fps = 0;
  FILE *f = nullptr;
  if (fopen_s(&f, (HarnessDir() + "\\framecap.txt").c_str(), "r") == 0 && f) {
    if (fscanf_s(f, "%d", &fps) != 1)
      fps = 0;
    fclose(f);
  }
  if (fps < 0 || fps > 1000)
    fps = 0;
  if (fps != g_capFps)
    Log("KAH: frame cap " + (fps ? Int(fps) + " fps" : std::string("off")));
  g_capFps = fps;
}

void FrameCap() {
  const DWORD tick = GetTickCount();
  if (g_capReadTick == 0 || tick - g_capReadTick > 1000) {
    g_capReadTick = tick;
    ReadFrameCap();
  }
  if (g_capFps <= 0 || g_qpcFreq <= 0.0) {
    g_capNext.QuadPart = 0;
    return;
  }
  const long long period = (long long)(g_qpcFreq / g_capFps);
  LARGE_INTEGER now;
  QueryPerformanceCounter(&now);
  if (g_capNext.QuadPart == 0 || now.QuadPart - g_capNext.QuadPart > period) {
    g_capNext.QuadPart = now.QuadPart + period; // first frame or a long frame: no catch-up burst
    return;
  }
  long long left = g_capNext.QuadPart - now.QuadPart;
  if (left > 0) {
    if (!g_capTimer) { // CREATE_WAITABLE_TIMER_HIGH_RESOLUTION (Win10 1803+), else a normal timer;
      // looked up at run time (the VS2010/SDK 7.1 headers target XP)
      typedef HANDLE(WINAPI * CreateTimerEx)(LPSECURITY_ATTRIBUTES, LPCWSTR, DWORD, DWORD);
      CreateTimerEx create =
          (CreateTimerEx)GetProcAddress(GetModuleHandleA("kernel32.dll"), "CreateWaitableTimerExW");
      if (create)
        g_capTimer = create(nullptr, nullptr, 0x00000002, 0x1F0003 /* TIMER_ALL_ACCESS */);
      if (!g_capTimer)
        g_capTimer = CreateWaitableTimerW(nullptr, FALSE, nullptr);
    }
    LARGE_INTEGER due;
    due.QuadPart = -(long long)((double)left / g_qpcFreq * 1e7); // relative, 100 ns units
    if (g_capTimer && SetWaitableTimer(g_capTimer, &due, 0, nullptr, nullptr, FALSE))
      WaitForSingleObject(g_capTimer, 100);
    else
      Sleep((DWORD)((double)left / g_qpcFreq * 1000.0));
  }
  g_capNext.QuadPart += period;
}

int FrameCapFps() { return g_capFps; }

// Per-frame work (fps timing, production sampling). Run m13: in Kenshi only
// the MyGUI frame event fires, Ogre's frameStarted never did, so timing fed
// from there stayed at 0 frames. Both sources call this; once Ogre frames
// are seen they win and the MyGUI ones are skipped (no double counting).
bool g_ogreFrames = false;
long long g_framesSinceLaunch = 0;

void FrameWork(bool fromOgre) {
  if (fromOgre)
    g_ogreFrames = true;
  else if (g_ogreFrames)
    return;
  // cap here, not only in frameStarted: in Kenshi only the MyGUI frame event
  // fires (GFXM 2026-10-10: framecap.txt=60, harness log cap=0 source=mygui)
  FrameCap();
  MeasureFrame();
  InputIsolationTick();
  SampleProduction(ou);
  KeepSuppliedPowered();
  // The keepers move, heal, teleport (pin) and order characters: at the safe
  // point when it fires (see Hook_ProcessThreadMessages), here otherwise.
  // From frameStarted they raced the world thread like the commands did
  // (5090 batch K: NavMesh thread crash in findPath, exe+0x3AADAD, 6 s after
  // a frameStarted "ko" on a fighting bandit, 2026-10-07).
  if (!SafePointActive())
    WorldKeepers();
  if (++g_framesSinceLaunch % 600 == 0)
    Log("KAH: fps frames=" + Int(g_framesSinceLaunch) + " source=" + (fromOgre ? "ogre" : "mygui") +
        " window: " + g_frameStats.Report() + " cap=" + Int(g_capFps));
}

void WorldKeepers() {
  KeepProtected();
  KeepTurretAim();
  KeepWalkTimers();
}

class AutomationFrameListener : public Ogre::FrameListener {
public:
  virtual bool frameStarted(const Ogre::FrameEvent &) {
    FrameWork(true);
    Tick("ogre");
    return true;
  }
};

AutomationFrameListener g_frameListener;

} // namespace

std::string FpsReport(bool reset) {
  const std::string out = g_frameStats.Report() + " cap=" + Int(FrameCapFps());
  if (reset)
    g_frameStats.Reset();
  return out;
}

namespace {

void OnGuiFrame(float) {
  FrameWork(false);
  Tick("mygui");
}

// On-screen player messages ("X is attacking!", "Saving...", "Research
// complete: X"), kept so tests can check them (KAH 2).
// GameWorld::showPlayerAMessage is a 12-byte stub (mov rcx,[this+0x4E0];
// jmp MessageRoller::add) and showPlayerAMessage_withLog calls the same
// MessageRoller function; the game's ~130 own call sites go through those two,
// mods through KenshiLib's exports. Hooking the MessageRoller function catches
// all of them in one place. If its address can't be read from the stub (the
// bytes differ: other build, or someone hooked the stub first) the two GameWorld
// functions are hooked instead.
typedef void(__fastcall *ShowMessageFn)(GameWorld *, const std::string &, bool);
typedef void(__fastcall *RollerAddFn)(void *, const std::string &, bool);
ShowMessageFn g_showMessageOrig = nullptr;
ShowMessageFn g_showMessageLogOrig = nullptr;
RollerAddFn g_rollerAddOrig = nullptr;
bool g_messageDedupe = true; // only the GameWorld fallback sees one message twice
std::string g_messageHookPoint = "none";
CRITICAL_SECTION g_messagesLock;
struct MessagesLockInit {
  MessagesLockInit() { InitializeCriticalSection(&g_messagesLock); }
} g_messagesLockInit;
std::vector<std::string> g_messages;

void RecordMessage(const std::string &message) {
  static std::string last;
  static DWORD lastTick = 0;
  DWORD now = GetTickCount();
  EnterCriticalSection(&g_messagesLock);
  if (!(g_messageDedupe && message == last && now - lastTick < 200)) { // _withLog may call the plain one
    SYSTEMTIME t;
    GetLocalTime(&t);
    char stamp[16];
    sprintf_s(stamp, "%02d:%02d:%02d ", t.wHour, t.wMinute, t.wSecond);
    g_messages.push_back(stamp + OneLine(message));
    if (g_messages.size() > 100)
      g_messages.erase(g_messages.begin());
  }
  last = message;
  lastTick = now;
  LeaveCriticalSection(&g_messagesLock);
}

void __fastcall Hook_ShowMessage(GameWorld *w, const std::string &message, bool queued) {
  RecordMessage(message);
  g_showMessageOrig(w, message, queued);
}

void __fastcall Hook_ShowMessageLog(GameWorld *w, const std::string &message, bool queued) {
  RecordMessage(message);
  g_showMessageLogOrig(w, message, queued);
}

void __fastcall Hook_RollerAdd(void *roller, const std::string &message, bool queued) {
  RecordMessage(message);
  g_rollerAddOrig(roller, message, queued);
}

// The MessageRoller function behind GameWorld::showPlayerAMessage: the stub is
// 48 8B 89 <disp32 0x4E0> (mov rcx,[rcx+0x4E0]) then E9 <rel32> (jmp), which
// may land on an incremental-link thunk (E9 <rel32>) first. 0 if the bytes differ.
unsigned char *MessageRollerAdd(__int64 showAddr) {
  const unsigned char *p = (const unsigned char *)showAddr;
  if (!p || IsBadReadPtr(p, 12))
    return nullptr;
  if (!(p[0] == 0x48 && p[1] == 0x8B && p[2] == 0x89 && *(const int *)(p + 3) == 0x4E0 && p[7] == 0xE9))
    return nullptr;
  unsigned char *q = (unsigned char *)(p + 12) + *(const int *)(p + 8);
  for (int hops = 0; hops < 4 && !IsBadReadPtr(q, 5) && q[0] == 0xE9; ++hops)
    q = q + 5 + *(const int *)(q + 1);
  return IsBadReadPtr(q, 16) ? nullptr : q;
}

// Test sessions must not overwrite the player's autosave slots: skip the
// autosave update while the harness is enabled (checked once a second).
typedef void(__fastcall *UpdateAutoSaveFn)(SaveManager *);
UpdateAutoSaveFn g_updateAutoSaveOrig = nullptr;

void __fastcall Hook_UpdateAutoSave(SaveManager *sm) {
  static DWORD lastCheck = 0;
  static bool testing = false;
  DWORD now = GetTickCount();
  if (now - lastCheck >= 1000) {
    lastCheck = now;
    bool was = testing;
    testing = HarnessEnabled();
    if (testing != was)
      Log(std::string("KAH: autosave ") + (testing ? "off (harness enabled)" : "on"));
  }
  if (!testing)
    g_updateAutoSaveOrig(sm);
}

// "power <b> supply": the town's grid resets and hands out power in
// updatePowerGrid; top the supplied buildings up right after it (KAH 10).
typedef void(__fastcall *UpdatePowerGridFn)(Town *);
UpdatePowerGridFn g_updatePowerGridOrig = nullptr;

void __fastcall Hook_UpdatePowerGrid(Town *town) {
  g_updatePowerGridOrig(town);
  KeepSuppliedPowered();
}

// "turret" (KAH 25): count turret shots per gun and target.
typedef void(__fastcall *GunShootFn)(GunClass *, Character *, RootObject *, StatsEnumerated, const Ogre::Vector3 &);
GunShootFn g_gunShootOrig = nullptr;

void __fastcall Hook_GunShoot(GunClass *gun, Character *me, RootObject *target, StatsEnumerated stat,
                              const Ogre::Vector3 &aimpos) {
  RecordGunShot(gun, me, target, (int)stat);
  RecordRangedShot(gun, me, target, (int)stat); // before the shot: the stats the shot code reads
  g_gunShootOrig(gun, me, target, stat, aimpos);
}

void InstallHooks() {
  __int64 shootAddr = KenshiLib::GetRealAddress(&GunClass::shoot);
  if (shootAddr) {
    int s = (int)KenshiLib::AddHook((void *)shootAddr, (void *)Hook_GunShoot, (void **)&g_gunShootOrig);
    Log("KAH: GunClass::shoot hook status=" + Int(s));
  } else {
    Log("KAH: GunClass::shoot not found; turret shot counts off");
  }
  __int64 gridAddr = KenshiLib::GetRealAddress(&Town::_NV_updatePowerGrid);
  if (gridAddr) {
    int s = (int)KenshiLib::AddHook((void *)gridAddr, (void *)Hook_UpdatePowerGrid,
                                    (void **)&g_updatePowerGridOrig);
    Log("KAH: Town::updatePowerGrid hook status=" + Int(s));
  } else {
    Log("KAH: Town::updatePowerGrid not found; power supply is per frame only");
  }
  __int64 autoSaveAddr = KenshiLib::GetRealAddress(&SaveManager::updateAutoSave);
  if (autoSaveAddr) {
    KenshiLib::HookStatus autoSaveStatus = KenshiLib::AddHook(
        (void *)autoSaveAddr, (void *)Hook_UpdateAutoSave, (void **)&g_updateAutoSaveOrig);
    Log("KAH: SaveManager::updateAutoSave hook status=" + Int((int)autoSaveStatus));
  } else {
    Log("KAH: SaveManager::updateAutoSave not found; autosave stays on");
  }
  __int64 gpuAddr = KenshiLib::GetRealAddress(&GameWorld::_NV_mainLoop_GPUSensitiveStuff);
  unsigned char *ptmAddr = ProcessThreadMessagesAddr(gpuAddr);
  if (ptmAddr) {
    int s = (int)KenshiLib::AddHook((void *)ptmAddr, (void *)Hook_ProcessThreadMessages,
                                    (void **)&g_processThreadMessagesOrig);
    g_safePointHooked = (s == 0 && g_processThreadMessagesOrig);
    char at[32];
    sprintf_s(at, "+0x%llX", (unsigned long long)(ptmAddr - (unsigned char *)GetModuleHandleA(nullptr)));
    Log(std::string("KAH: GameWorld::processThreadMessages hook (") + at + ") status=" + Int(s) +
        (g_safePointHooked ? "; world commands run after the world thread join" : ""));
  } else {
    Log("KAH: processThreadMessages call not found in mainLoop_GPUSensitiveStuff; commands run in "
        "frameStarted (racing the world thread)");
  }

  __int64 msgAddr = KenshiLib::GetRealAddress(&GameWorld::showPlayerAMessage);
  __int64 msgLogAddr = KenshiLib::GetRealAddress(&GameWorld::showPlayerAMessage_withLog);
  unsigned char *rollerAdd = MessageRollerAdd(msgAddr);
  int rollerStatus = -1;
  if (rollerAdd)
    rollerStatus = (int)KenshiLib::AddHook((void *)rollerAdd, (void *)Hook_RollerAdd, (void **)&g_rollerAddOrig);
  if (rollerAdd && rollerStatus == 0 && g_rollerAddOrig) {
    g_messageDedupe = false;
    char at[32];
    sprintf_s(at, "+0x%llX", (unsigned long long)(rollerAdd - (unsigned char *)GetModuleHandleA(nullptr)));
    g_messageHookPoint = std::string("MessageRoller") + at;
    Log("KAH: player message hook on MessageRoller (" + g_messageHookPoint + ") status=0");
  } else if (msgAddr && msgLogAddr) {
    if (rollerAdd)
      Log("KAH: MessageRoller hook status=" + Int(rollerStatus) + "; hooking the GameWorld functions instead");
    else
      Log("KAH: MessageRoller not found behind showPlayerAMessage; hooking the GameWorld functions instead");
    g_messageHookPoint = "GameWorld";
    int a = (int)KenshiLib::AddHook((void *)msgAddr, (void *)Hook_ShowMessage,
                                    (void **)&g_showMessageOrig);
    int b = (int)KenshiLib::AddHook((void *)msgLogAddr, (void *)Hook_ShowMessageLog,
                                    (void **)&g_showMessageLogOrig);
    Log("KAH: player message hooks status=" + Int(a) + "," + Int(b));
  } else {
    Log("KAH: player message functions not found; messages command off");
  }

  Ogre::Root *root = Ogre::Root::getSingletonPtr();
  if (!root) {
    Log("KAH: no Ogre::Root yet; automation commands off.");
    return;
  }
  root->addFrameListener(&g_frameListener);
  MyGUI::Gui *gui = MyGUI::Gui::getInstancePtr();
  if (gui)
    gui->eventFrameStart += MyGUI::newDelegate(&OnGuiFrame);
  Log("KAH: frame listener added (mygui=" + std::string(gui ? "yes" : "no") +
      " thread=" + Int(GetCurrentThreadId()) + ")");

  // Ogre stops rendering (and the game stops updating) while its window is
  // in the background; automated runs keep the game running unfocused.
  if (!HarnessEnabled() && !InputIsolationOn())
    return;
  int windows = 0;
  Ogre::RenderSystem *rs = root->getRenderSystem();
  if (rs) {
    Ogre::RenderSystem::RenderTargetIterator it = rs->getRenderTargetIterator();
    while (it.hasMoreElements()) {
      Ogre::RenderWindow *win = dynamic_cast<Ogre::RenderWindow *>(it.getNext());
      if (!win)
        continue;
      win->setDeactivateOnFocusChange(false);
      win->setActive(true);
      ++windows;
    }
  }
  Log("KAH: keep running in background: " + Int(windows) + " render window(s)");
}

} // namespace

std::string RecentMessages(int n) {
  if (n < 1)
    n = 10;
  EnterCriticalSection(&g_messagesLock);
  std::string out = Int((long long)g_messages.size()) + " message(s) since launch";
  size_t from = g_messages.size() > (size_t)n ? g_messages.size() - n : 0;
  for (size_t i = from; i < g_messages.size(); ++i)
    out += " | " + g_messages[i];
  LeaveCriticalSection(&g_messagesLock);
  if (!g_rollerAddOrig && !g_showMessageOrig)
    out += " (message hook not installed)";
  else
    out += " (hook: " + g_messageHookPoint + ")";
  return out;
}

// Grabs the game's last rendered frame (HUD and menus included) to
// <mod folder>\shots\<name>.png.
std::string TakeScreenshot(const std::string &name, bool &ok) {
  ok = false;
  Ogre::Root *root = Ogre::Root::getSingletonPtr();
  Ogre::RenderSystem *rs = root ? root->getRenderSystem() : nullptr;
  Ogre::RenderWindow *win = nullptr;
  if (rs) {
    Ogre::RenderSystem::RenderTargetIterator it = rs->getRenderTargetIterator();
    while (!win && it.hasMoreElements())
      win = dynamic_cast<Ogre::RenderWindow *>(it.getNext());
  }
  if (!win)
    return "no render window";
  const std::string dir = HarnessDir() + "\\shots";
  CreateDirectoryA(dir.c_str(), nullptr);
  std::string file = name;
  if (file.empty()) {
    SYSTEMTIME t;
    GetLocalTime(&t);
    char buf[32];
    sprintf_s(buf, "shot-%02d%02d%02d", t.wHour, t.wMinute, t.wSecond);
    file = buf;
  }
  const std::string path = dir + "\\" + file + ".png";
  try {
    win->writeContentsToFile(path);
  } catch (...) {
    return "screenshot failed: " + path;
  }
  ok = FileExists(path);
  Log("KAH: screenshot " + path + " ok=" + (ok ? "1" : "0"));
  return (ok ? "" : "screenshot not written: ") + path + " (" + Int(win->getWidth()) + "x" +
         Int(win->getHeight()) + ")";
}

// RE_Kenshi plugin entry point.
__declspec(dllexport) void startPlugin() {
  // A fresh log per game session (tooling waits for lines of this session).
  DeleteFileA((HarnessDir() + "\\harness.log").c_str());
  Log("KAH: Kenshi Automation Harness starting (dir=" + HarnessDir() +
      " enabled=" + (HarnessEnabled() ? "1" : "0") + ")");
  InputIsolationStartup();
  InstallHooks();
}
