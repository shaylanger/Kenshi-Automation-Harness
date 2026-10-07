// Input isolation: while automated tests run, the game must not grab the
// user's cursor or keys, and must keep running in the background.
//
// When isolation is ON (command "input_isolation on", or input_isolation.flag
// in the mod folder at startup):
//  - user32 ClipCursor / SetCursorPos / SetForegroundWindow are no-ops; the
//    cursor the game sees (GetCursorPos) is a virtual one inside its window.
//  - GetAsyncKeyState / GetKeyState / GetKeyboardState report only keys the
//    harness injected (key_inject / mouse_inject); GetForegroundWindow returns
//    the game window (the game and other mods behave as if focused).
//  - DirectInput8 GetDeviceState / GetDeviceData (keyboard + mouse, so OIS
//    and KenshiFP's own mouse device) return only injected data; the devices
//    are unacquired once so an exclusive mouse never holds the real one.
//  - Real WM_KEY* / WM_*CHAR / mouse messages / WM_INPUT reaching the game
//    window are dropped; clicks don't activate it (WM_MOUSEACTIVATE); losing
//    focus (WM_ACTIVATEAPP/WM_ACTIVATE/WM_KILLFOCUS) is hidden from the game,
//    and a minimize is undone without activating the window.
//  - Escape hatch for a human at the game window: Ctrl+Alt+Shift+F12 turns
//    isolation off.
// Other mods can ask with the exported KAH_InputIsolated() (1 = on).
// <mod folder>\input_isolation.on exists while isolation is on (tools such as
// kenshi-key.ps1 switch to the injection commands then).

#include "Harness.h"
#include "InputInject.h"

#define DIRECTINPUT_VERSION 0x0800
#include <windows.h>
#include <dinput.h>

#include <core/Functions.h>

#include <string>
#include <vector>

namespace {

CRITICAL_SECTION g_lock;
volatile LONG g_lockReady = 0;
volatile LONG g_on = 0;
LONG g_epoch = 0;
HWND g_hwnd = nullptr;
WNDPROC g_prevProc = nullptr;
bool g_procUnicode = true;
bool g_hooksTried = false;
int g_user32Hooks = 0, g_user32Wanted = 0, g_diHooks = 0, g_diWanted = 0;
long long g_frames = 0;
std::string g_lastOnReason;

inject::HeldState g_held;
POINT g_virt = {0, 0}; // virtual cursor, client coordinates

enum DevType { kDevUnknown = 0, kDevKeyboard = 1, kDevMouse = 2, kDevOther = 3 };
struct Device {
  void *dev;
  int type;
  LONG epoch;
  long dx, dy, dz;
  inject::EventQueue q;
};
const int kMaxDevices = 16;
Device g_devices[kMaxDevices];
int g_deviceCount = 0;
unsigned long g_seq = 0;

struct Release {
  DWORD due;
  bool mouse;
  int code;
};
std::vector<Release> g_releases;

volatile LONG g_droppedMsgs = 0, g_droppedDi = 0, g_blockedClip = 0, g_blockedSetCursor = 0,
              g_blockedForeground = 0, g_hiddenDeactivate = 0, g_restoredMinimized = 0,
              g_injectedKeys = 0, g_injectedMouse = 0;

void Lock() {
  if (InterlockedCompareExchange(&g_lockReady, 1, 0) == 0)
    InitializeCriticalSection(&g_lock), InterlockedExchange(&g_lockReady, 2);
  while (g_lockReady != 2)
    Sleep(0);
  EnterCriticalSection(&g_lock);
}
void Unlock() { LeaveCriticalSection(&g_lock); }

std::string Hex(unsigned long long v) {
  char b[32];
  sprintf_s(b, "0x%llX", v);
  return b;
}

// ---- user32 hooks ----
typedef SHORT(WINAPI *GetAsyncKeyStateFn)(int);
typedef SHORT(WINAPI *GetKeyStateFn)(int);
typedef BOOL(WINAPI *GetKeyboardStateFn)(PBYTE);
typedef BOOL(WINAPI *GetCursorPosFn)(LPPOINT);
typedef BOOL(WINAPI *SetCursorPosFn)(int, int);
typedef BOOL(WINAPI *ClipCursorFn)(const RECT *);
typedef BOOL(WINAPI *SetForegroundWindowFn)(HWND);
typedef HWND(WINAPI *GetForegroundWindowFn)(void);
GetAsyncKeyStateFn g_gaksOrig = nullptr;
GetKeyStateFn g_gksOrig = nullptr;
GetKeyboardStateFn g_gkbsOrig = nullptr;
GetCursorPosFn g_gcpOrig = nullptr;
SetCursorPosFn g_scpOrig = nullptr;
ClipCursorFn g_clipOrig = nullptr;
SetForegroundWindowFn g_sfwOrig = nullptr;
GetForegroundWindowFn g_gfwOrig = nullptr;

bool Held(int vk) { return vk >= 0 && vk < 256 && g_held.vk[vk] != 0; }

SHORT WINAPI H_GetAsyncKeyState(int vk) {
  if (!g_on)
    return g_gaksOrig(vk);
  return Held(vk) ? (SHORT)0x8000 : (SHORT)0;
}
SHORT WINAPI H_GetKeyState(int vk) {
  if (!g_on)
    return g_gksOrig(vk);
  return Held(vk) ? (SHORT)0xFF80 : (SHORT)0;
}
BOOL WINAPI H_GetKeyboardState(PBYTE keys) {
  if (!g_on || !keys)
    return g_gkbsOrig(keys);
  for (int i = 0; i < 256; ++i)
    keys[i] = g_held.vk[i] ? 0x80 : 0;
  return TRUE;
}
BOOL WINAPI H_GetCursorPos(LPPOINT p) {
  if (!g_on || !g_hwnd || !p)
    return g_gcpOrig(p);
  POINT v = g_virt;
  ClientToScreen(g_hwnd, &v);
  *p = v;
  return TRUE;
}
BOOL WINAPI H_SetCursorPos(int x, int y) {
  if (!g_on || !g_hwnd)
    return g_scpOrig(x, y);
  POINT p = {x, y};
  ScreenToClient(g_hwnd, &p);
  g_virt = p;
  InterlockedIncrement(&g_blockedSetCursor);
  return TRUE;
}
BOOL WINAPI H_ClipCursor(const RECT *r) {
  if (!g_on || !r)
    return g_clipOrig(r);
  InterlockedIncrement(&g_blockedClip);
  return TRUE;
}
BOOL WINAPI H_SetForegroundWindow(HWND h) {
  if (!g_on)
    return g_sfwOrig(h);
  InterlockedIncrement(&g_blockedForeground);
  return TRUE;
}
HWND WINAPI H_GetForegroundWindow(void) {
  if (g_on && g_hwnd)
    return g_hwnd;
  return g_gfwOrig();
}

HWND RealForeground() { return g_gfwOrig ? g_gfwOrig() : GetForegroundWindow(); }
SHORT RealAsyncKey(int vk) { return g_gaksOrig ? g_gaksOrig(vk) : GetAsyncKeyState(vk); }

// ---- DirectInput hooks ----
typedef HRESULT(WINAPI *GetDeviceStateFn)(void *, DWORD, LPVOID);
typedef HRESULT(WINAPI *GetDeviceDataFn)(void *, DWORD, void *, DWORD *, DWORD);
typedef HRESULT(WINAPI *GetCapabilitiesFn)(void *, DIDEVCAPS *);
typedef HRESULT(WINAPI *UnacquireFn)(void *);
const int kMaxDiTargets = 4;
GetDeviceStateFn g_gdsOrig[kMaxDiTargets];
GetDeviceDataFn g_gddOrig[kMaxDiTargets];

Device *FindDevice(void *dev) {
  for (int i = 0; i < g_deviceCount; ++i)
    if (g_devices[i].dev == dev)
      return &g_devices[i];
  return nullptr;
}

Device *Track(void *dev, int hintType) {
  Lock();
  Device *d = FindDevice(dev);
  Unlock();
  if (d)
    return d;
  int type = hintType;
  DIDEVCAPS caps;
  ZeroMemory(&caps, sizeof(caps));
  caps.dwSize = sizeof(caps);
  GetCapabilitiesFn getCaps = (GetCapabilitiesFn)(*(void ***)dev)[3];
  if (SUCCEEDED(getCaps(dev, &caps))) {
    int t = (int)(caps.dwDevType & 0xFF);
    type = t == DI8DEVTYPE_KEYBOARD ? kDevKeyboard : t == DI8DEVTYPE_MOUSE ? kDevMouse : kDevOther;
  }
  Lock();
  d = FindDevice(dev);
  if (!d && g_deviceCount < kMaxDevices) {
    d = &g_devices[g_deviceCount++];
    d->dev = dev;
    d->type = type;
    d->epoch = 0;
    d->dx = d->dy = d->dz = 0;
    d->q.Clear();
    Log(std::string("KAH: input isolation: DirectInput device ") + Hex((unsigned long long)dev) + " type=" +
        (type == kDevKeyboard ? "keyboard" : type == kDevMouse ? "mouse" : "other"));
  }
  Unlock();
  return d;
}

// Once per "isolation on": unacquire, so an exclusive device lets go of the
// real mouse/keyboard (the game re-acquires by itself after "off").
void EnsureReleased(Device *d, void *dev) {
  if (!d || d->epoch == g_epoch)
    return;
  d->epoch = g_epoch;
  ((UnacquireFn)(*(void ***)dev)[8])(dev);
}

HRESULT GetDeviceStateCommon(GetDeviceStateFn orig, void *dev, DWORD cb, LPVOID data) {
  Device *d = Track(dev, cb == 256 ? kDevKeyboard : kDevMouse); // known before isolation turns on
  if (!g_on)
    return orig(dev, cb, data);
  EnsureReleased(d, dev);
  if (!data)
    return DIERR_INVALIDPARAM;
  unsigned char scratch[512];
  if (cb <= sizeof(scratch) && SUCCEEDED(orig(dev, cb, scratch))) {
    for (DWORD i = 0; i < cb; ++i)
      if (scratch[i]) {
        InterlockedIncrement(&g_droppedDi);
        break;
      }
  }
  int type = d ? d->type : (cb == 256 ? kDevKeyboard : kDevMouse);
  if (type == kDevKeyboard) {
    inject::FillKeyboardState(g_held, data, cb);
  } else if (type == kDevMouse) {
    long dx = 0, dy = 0, dz = 0;
    Lock();
    if (d) {
      dx = d->dx, dy = d->dy, dz = d->dz;
      d->dx = d->dy = d->dz = 0;
    }
    Unlock();
    inject::FillMouseState(g_held, dx, dy, dz, data, cb);
  } else {
    memset(data, 0, cb);
  }
  return DI_OK;
}

HRESULT GetDeviceDataCommon(GetDeviceDataFn orig, void *dev, DWORD cb, void *items, DWORD *n, DWORD flags) {
  Device *d = Track(dev, kDevUnknown);
  if (!g_on)
    return orig(dev, cb, items, n, flags);
  if (!n)
    return DIERR_INVALIDPARAM;
  EnsureReleased(d, dev);
  if (!(flags & DIGDD_PEEK)) { // drain whatever real input the device still holds
    DIDEVICEOBJECTDATA tmp[64];
    DWORD got = 64;
    if (SUCCEEDED(orig(dev, sizeof(DIDEVICEOBJECTDATA), tmp, &got, 0)) && got)
      InterlockedExchangeAdd(&g_droppedDi, (LONG)got);
  }
  if (!d) {
    *n = 0;
    return DI_OK;
  }
  Lock();
  unsigned long count = *n;
  d->q.Take(cb, items, &count, (flags & DIGDD_PEEK) != 0);
  Unlock();
  *n = count;
  return DI_OK;
}

// One detour per hooked address (the A and W devices may use different code).
#define KAH_DI_DETOURS(N)                                                                                     \
  HRESULT WINAPI GdsDetour##N(void *dev, DWORD cb, LPVOID data) {                                             \
    return GetDeviceStateCommon(g_gdsOrig[N], dev, cb, data);                                                 \
  }                                                                                                           \
  HRESULT WINAPI GddDetour##N(void *dev, DWORD cb, void *items, DWORD *n, DWORD flags) {                      \
    return GetDeviceDataCommon(g_gddOrig[N], dev, cb, items, n, flags);                                       \
  }
KAH_DI_DETOURS(0)
KAH_DI_DETOURS(1)
KAH_DI_DETOURS(2)
KAH_DI_DETOURS(3)
void *const kGdsDetours[kMaxDiTargets] = {(void *)&GdsDetour0, (void *)&GdsDetour1, (void *)&GdsDetour2,
                                          (void *)&GdsDetour3};
void *const kGddDetours[kMaxDiTargets] = {(void *)&GddDetour0, (void *)&GddDetour1, (void *)&GddDetour2,
                                          (void *)&GddDetour3};

const GUID kIidDi8A = {0xBF798030, 0x483A, 0x4DA2, {0xAA, 0x99, 0x5D, 0x64, 0xED, 0x36, 0x97, 0x00}};
const GUID kIidDi8W = {0xBF798031, 0x483A, 0x4DA2, {0xAA, 0x99, 0x5D, 0x64, 0xED, 0x36, 0x97, 0x00}};
const GUID kGuidSysMouse = {0x6F1D2B60, 0xD5A0, 0x11CF, {0xBF, 0xC7, 0x44, 0x45, 0x53, 0x54, 0x00, 0x00}};
const GUID kGuidSysKeyboard = {0x6F1D2B61, 0xD5A0, 0x11CF, {0xBF, 0xC7, 0x44, 0x45, 0x53, 0x54, 0x00, 0x00}};
typedef HRESULT(WINAPI *DirectInput8CreateFn)(HINSTANCE, DWORD, REFIID, LPVOID *, LPUNKNOWN);
typedef HRESULT(WINAPI *CreateDeviceFn)(void *, REFGUID, void **, LPUNKNOWN);
typedef ULONG(WINAPI *ReleaseFn)(void *);

// The device method addresses (vtable slots 9 = GetDeviceState, 10 =
// GetDeviceData) of the A and W keyboard and mouse devices; hooking the code
// covers every device of the process, whoever created it.
void HookDirectInput() {
  HMODULE dll = LoadLibraryA("dinput8.dll");
  DirectInput8CreateFn create = dll ? (DirectInput8CreateFn)GetProcAddress(dll, "DirectInput8Create") : nullptr;
  if (!create) {
    Log("KAH: input isolation: dinput8 not available; DirectInput not isolated");
    return;
  }
  void *gds[kMaxDiTargets * 2], *gdd[kMaxDiTargets * 2];
  int nGds = 0, nGdd = 0;
  const GUID *iids[2] = {&kIidDi8A, &kIidDi8W};
  const GUID *devs[2] = {&kGuidSysKeyboard, &kGuidSysMouse};
  for (int i = 0; i < 2; ++i) {
    void *di = nullptr;
    if (FAILED(create(GetModuleHandleA(nullptr), DIRECTINPUT_VERSION, *iids[i], &di, nullptr)) || !di)
      continue;
    for (int j = 0; j < 2; ++j) {
      void *dev = nullptr;
      if (FAILED(((CreateDeviceFn)(*(void ***)di)[3])(di, *devs[j], &dev, nullptr)) || !dev)
        continue;
      void *s = (*(void ***)dev)[9], *g = (*(void ***)dev)[10];
      bool haveS = false, haveG = false;
      for (int k = 0; k < nGds; ++k)
        haveS = haveS || gds[k] == s;
      for (int k = 0; k < nGdd; ++k)
        haveG = haveG || gdd[k] == g;
      if (!haveS && nGds < kMaxDiTargets)
        gds[nGds++] = s;
      if (!haveG && nGdd < kMaxDiTargets)
        gdd[nGdd++] = g;
      ((ReleaseFn)(*(void ***)dev)[2])(dev);
    }
    ((ReleaseFn)(*(void ***)di)[2])(di);
  }
  g_diWanted = nGds + nGdd;
  std::string at;
  HMODULE base = dll;
  for (int k = 0; k < nGds; ++k) {
    int s = (int)KenshiLib::AddHook(gds[k], kGdsDetours[k], (void **)&g_gdsOrig[k]);
    if (s == 0 && g_gdsOrig[k])
      ++g_diHooks;
    at += " GetDeviceState@+" + Hex((unsigned long long)((char *)gds[k] - (char *)base)) + "=" + Int(s);
  }
  for (int k = 0; k < nGdd; ++k) {
    int s = (int)KenshiLib::AddHook(gdd[k], kGddDetours[k], (void **)&g_gddOrig[k]);
    if (s == 0 && g_gddOrig[k])
      ++g_diHooks;
    at += " GetDeviceData@+" + Hex((unsigned long long)((char *)gdd[k] - (char *)base)) + "=" + Int(s);
  }
  Log("KAH: input isolation: dinput8 hooks " + Int(g_diHooks) + "/" + Int(g_diWanted) + at);
}

void HookUser32() {
  HMODULE u = GetModuleHandleA("user32.dll");
  struct Target {
    const char *name;
    void *detour;
    void **orig;
  } targets[] = {
      {"GetAsyncKeyState", (void *)&H_GetAsyncKeyState, (void **)&g_gaksOrig},
      {"GetKeyState", (void *)&H_GetKeyState, (void **)&g_gksOrig},
      {"GetKeyboardState", (void *)&H_GetKeyboardState, (void **)&g_gkbsOrig},
      {"GetCursorPos", (void *)&H_GetCursorPos, (void **)&g_gcpOrig},
      {"SetCursorPos", (void *)&H_SetCursorPos, (void **)&g_scpOrig},
      {"ClipCursor", (void *)&H_ClipCursor, (void **)&g_clipOrig},
      {"SetForegroundWindow", (void *)&H_SetForegroundWindow, (void **)&g_sfwOrig},
      {"GetForegroundWindow", (void *)&H_GetForegroundWindow, (void **)&g_gfwOrig},
  };
  std::string failed;
  g_user32Wanted = (int)(sizeof(targets) / sizeof(targets[0]));
  for (int i = 0; i < g_user32Wanted; ++i) {
    void *addr = u ? (void *)GetProcAddress(u, targets[i].name) : nullptr;
    int s = addr ? (int)KenshiLib::AddHook(addr, targets[i].detour, targets[i].orig) : -1;
    if (s == 0 && *targets[i].orig)
      ++g_user32Hooks;
    else
      failed += std::string(" ") + targets[i].name + "=" + Int(s);
  }
  Log("KAH: input isolation: user32 hooks " + Int(g_user32Hooks) + "/" + Int(g_user32Wanted) +
      (failed.empty() ? "" : " failed:" + failed));
}

// A hook that failed leaves its original pointer NULL: the detour must then
// never run. AddHook either installs it (original set) or doesn't patch.
void EnsureHooks() {
  if (g_hooksTried)
    return;
  g_hooksTried = true;
  HookUser32();
  HookDirectInput();
}

// ---- window ----
LRESULT CALLBACK IsoWndProc(HWND h, UINT m, WPARAM w, LPARAM l);

BOOL CALLBACK FindGameWindow(HWND h, LPARAM out) {
  DWORD pid = 0;
  GetWindowThreadProcessId(h, &pid);
  if (pid != GetCurrentProcessId())
    return TRUE;
  char cls[64] = {0};
  GetClassNameA(h, cls, sizeof(cls));
  if (strncmp(cls, "OgreD3D", 7) != 0)
    return TRUE;
  *(HWND *)out = h;
  return FALSE;
}

void AttachWindow() {
  if (g_prevProc)
    return;
  HWND h = nullptr;
  EnumWindows(&FindGameWindow, (LPARAM)&h);
  if (!h)
    return;
  g_procUnicode = IsWindowUnicode(h) != 0;
  g_hwnd = h;
  RECT rc;
  if (GetClientRect(h, &rc)) {
    g_virt.x = (rc.right - rc.left) / 2;
    g_virt.y = (rc.bottom - rc.top) / 2;
  }
  g_prevProc = (WNDPROC)(g_procUnicode ? SetWindowLongPtrW(h, GWLP_WNDPROC, (LONG_PTR)&IsoWndProc)
                                       : SetWindowLongPtrA(h, GWLP_WNDPROC, (LONG_PTR)&IsoWndProc));
  Log("KAH: input isolation: game window " + Hex((unsigned long long)h) + " subclassed=" +
      (g_prevProc ? "1" : "0"));
}

LRESULT CallPrev(HWND h, UINT m, WPARAM w, LPARAM l) {
  return g_procUnicode ? CallWindowProcW(g_prevProc, h, m, w, l) : CallWindowProcA(g_prevProc, h, m, w, l);
}
LRESULT CallDef(HWND h, UINT m, WPARAM w, LPARAM l) {
  return g_procUnicode ? DefWindowProcW(h, m, w, l) : DefWindowProcA(h, m, w, l);
}

void WriteMarker(bool on) {
  const std::string path = HarnessDir() + "\\input_isolation.on";
  if (!on) {
    DeleteFileA(path.c_str());
    return;
  }
  HANDLE f = CreateFileA(path.c_str(), GENERIC_WRITE, FILE_SHARE_READ, nullptr, CREATE_ALWAYS, 0, nullptr);
  if (f != INVALID_HANDLE_VALUE) {
    char pid[32];
    sprintf_s(pid, "pid=%lu\r\n", GetCurrentProcessId());
    DWORD wr = 0;
    WriteFile(f, pid, (DWORD)strlen(pid), &wr, nullptr);
    CloseHandle(f);
  }
}

void SetIsolation(bool on, const std::string &why) {
  Lock();
  bool was = g_on != 0;
  if (on != was) {
    g_held.Reset();
    g_releases.clear();
    for (int i = 0; i < g_deviceCount; ++i) {
      g_devices[i].q.Clear();
      g_devices[i].dx = g_devices[i].dy = g_devices[i].dz = 0;
    }
    if (on)
      ++g_epoch;
    InterlockedExchange(&g_on, on ? 1 : 0);
  }
  Unlock();
  if (on == was)
    return;
  if (on) {
    g_lastOnReason = why;
    if (g_clipOrig)
      g_clipOrig(nullptr); // let go of any clip the game set before
    ReleaseCapture();
  }
  WriteMarker(on);
  Log(std::string("KAH: input isolation ") + (on ? "ON" : "OFF") + " (" + why + ")");
}

bool IsKeyMsg(UINT m) { return m >= WM_KEYFIRST && m <= WM_KEYLAST; }
bool IsMouseMsg(UINT m) { return m >= WM_MOUSEFIRST && m <= WM_MOUSELAST; }

LRESULT CALLBACK IsoWndProc(HWND h, UINT m, WPARAM w, LPARAM l) {
  if (g_on) {
    if ((m == WM_KEYDOWN || m == WM_SYSKEYDOWN) && w == VK_F12 && (RealAsyncKey(VK_CONTROL) & 0x8000) &&
        (RealAsyncKey(VK_MENU) & 0x8000) && (RealAsyncKey(VK_SHIFT) & 0x8000)) {
      SetIsolation(false, "Ctrl+Alt+Shift+F12 at the game window");
      return 0;
    }
    if (IsKeyMsg(m) || IsMouseMsg(m)) {
      InterlockedIncrement(&g_droppedMsgs);
      return 0;
    }
    switch (m) {
    case WM_INPUT:
      InterlockedIncrement(&g_droppedMsgs);
      return CallDef(h, m, w, l);
    case WM_MOUSEACTIVATE:
      return MA_NOACTIVATEANDEAT;
    case WM_ACTIVATEAPP:
      if (!w) {
        InterlockedIncrement(&g_hiddenDeactivate);
        return 0;
      }
      break;
    case WM_ACTIVATE:
      if (LOWORD(w) == WA_INACTIVE) {
        InterlockedIncrement(&g_hiddenDeactivate);
        return CallDef(h, m, w, l);
      }
      break;
    case WM_KILLFOCUS:
      InterlockedIncrement(&g_hiddenDeactivate);
      return 0;
    case WM_SIZE:
      if (w == SIZE_MINIMIZED) {
        InterlockedIncrement(&g_restoredMinimized);
        ShowWindowAsync(h, SW_SHOWNOACTIVATE);
        return 0;
      }
      break;
    }
  }
  return CallPrev(h, m, w, l);
}

// ---- injection ----
void PushToDevices(int type, unsigned long ofs, unsigned long data) {
  inject::ObjData e;
  e.dwOfs = ofs;
  e.dwData = data;
  e.dwTimeStamp = GetTickCount();
  e.uAppData = 0;
  for (int i = 0; i < g_deviceCount; ++i)
    if (g_devices[i].type == type) {
      e.dwSequence = ++g_seq;
      g_devices[i].q.Push(e);
    }
}

int LeftOf(int vk) {
  if (vk == VK_SHIFT) return VK_LSHIFT;
  if (vk == VK_CONTROL) return VK_LCONTROL;
  if (vk == VK_MENU) return VK_LMENU;
  return 0;
}

void KeyEvent(int vk, bool down) { // caller holds the lock
  g_held.vk[vk] = down ? 1 : 0;
  int other = inject::GenericModifier(vk);
  if (!other)
    other = LeftOf(vk);
  if (other)
    g_held.vk[other] = down ? 1 : 0;
  int dik = inject::VkToDik(vk, (int)MapVirtualKeyA((UINT)vk, 0 /* MAPVK_VK_TO_VSC */));
  if (dik > 0 && dik < 256) {
    g_held.dik[dik] = down ? 1 : 0;
    PushToDevices(kDevKeyboard, (unsigned long)dik, down ? 0x80 : 0);
  }
  InterlockedIncrement(&g_injectedKeys);
}

const int kButtonVk[5] = {VK_LBUTTON, VK_RBUTTON, VK_MBUTTON, VK_XBUTTON1, VK_XBUTTON2};

void ButtonEvent(int b, bool down) { // caller holds the lock
  g_held.button[b] = down ? 1 : 0;
  g_held.vk[kButtonVk[b]] = down ? 1 : 0;
  PushToDevices(kDevMouse, inject::kMouseButton0 + (unsigned long)b, down ? 0x80 : 0);
  InterlockedIncrement(&g_injectedMouse);
}

void ClampVirt() {
  RECT rc;
  if (!g_hwnd || !GetClientRect(g_hwnd, &rc))
    return;
  if (g_virt.x < 0) g_virt.x = 0;
  if (g_virt.y < 0) g_virt.y = 0;
  if (g_virt.x >= rc.right) g_virt.x = rc.right > 0 ? rc.right - 1 : 0;
  if (g_virt.y >= rc.bottom) g_virt.y = rc.bottom > 0 ? rc.bottom - 1 : 0;
}

// Relative motion: DirectInput events (OIS) and, when state, the
// GetDeviceState accumulators (KenshiFP's look) too; moves the virtual cursor.
void MoveEvent(long dx, long dy, bool state) { // caller holds the lock
  PushToDevices(kDevMouse, inject::kMouseX, (unsigned long)dx);
  if (dy)
    PushToDevices(kDevMouse, inject::kMouseY, (unsigned long)dy);
  if (state)
    for (int i = 0; i < g_deviceCount; ++i)
      if (g_devices[i].type == kDevMouse)
        g_devices[i].dx += dx, g_devices[i].dy += dy;
  g_virt.x += dx;
  g_virt.y += dy;
  ClampVirt();
  InterlockedIncrement(&g_injectedMouse);
}

void WheelEvent(long dz) { // caller holds the lock
  PushToDevices(kDevMouse, inject::kMouseZ, (unsigned long)dz);
  for (int i = 0; i < g_deviceCount; ++i)
    if (g_devices[i].type == kDevMouse)
      g_devices[i].dz += dz;
  InterlockedIncrement(&g_injectedMouse);
}

int CountDevices(int type) {
  int n = 0;
  for (int i = 0; i < g_deviceCount; ++i)
    n += g_devices[i].type == type ? 1 : 0;
  return n;
}

std::string MonitorOf(HWND h) {
  if (!h)
    return "?";
  HMONITOR mon = MonitorFromWindow(h, MONITOR_DEFAULTTONULL);
  if (!mon)
    return "none";
  MONITORINFOEXA mi;
  mi.cbSize = sizeof(mi);
  if (!GetMonitorInfoA(mon, &mi))
    return "?";
  return mi.szDevice;
}

std::string Status() {
  std::string held;
  Lock();
  for (int i = 1; i < 256; ++i)
    if (g_held.vk[i])
      held += (held.empty() ? "" : ",") + Hex((unsigned long long)i);
  POINT v = g_virt;
  int kbd = CountDevices(kDevKeyboard), mouse = CountDevices(kDevMouse), other = g_deviceCount - kbd - mouse;
  Unlock();
  HWND fg = RealForeground();
  std::string win = "?";
  RECT wr;
  if (g_hwnd && GetWindowRect(g_hwnd, &wr))
    win = Int(wr.left) + "," + Int(wr.top) + "," + Int(wr.right - wr.left) + "x" + Int(wr.bottom - wr.top);
  return std::string("isolation=") + (g_on ? "on" : "off") + " hooks=user32:" + Int(g_user32Hooks) + "/" +
         Int(g_user32Wanted) + ",dinput:" + Int(g_diHooks) + "/" + Int(g_diWanted) +
         " wndproc=" + (g_prevProc ? "1" : "0") + " devices=kbd:" + Int(kbd) + ",mouse:" + Int(mouse) +
         ",other:" + Int(other) + " dropped_msgs=" + Int(g_droppedMsgs) + " dropped_di=" + Int(g_droppedDi) +
         " blocked_clip=" + Int(g_blockedClip) + " blocked_setcursor=" + Int(g_blockedSetCursor) +
         " blocked_foreground=" + Int(g_blockedForeground) + " hidden_deactivate=" + Int(g_hiddenDeactivate) +
         " restored_minimized=" + Int(g_restoredMinimized) + " injected_keys=" + Int(g_injectedKeys) +
         " injected_mouse=" + Int(g_injectedMouse) + " held=" + (held.empty() ? "none" : held) +
         " cursor=" + Int(v.x) + "," + Int(v.y) + " frames=" + Int(g_frames) +
         " focused=" + (g_hwnd && fg == g_hwnd ? "1" : "0") + " iconic=" + (g_hwnd && IsIconic(g_hwnd) ? "1" : "0") +
         " window=" + win + " monitor=" + MonitorOf(g_hwnd);
}

bool ParseButton(const std::string &s, int &b) {
  const std::string v = Lower(s);
  if (v == "left" || v == "lmb") b = 0;
  else if (v == "right" || v == "rmb") b = 1;
  else if (v == "middle" || v == "mmb") b = 2;
  else if (v == "x1") b = 3;
  else if (v == "x2") b = 4;
  else return false;
  return true;
}

bool ParseInt(const std::string &s, long &v) {
  if (s.empty())
    return false;
  char *end = nullptr;
  v = strtol(s.c_str(), &end, 10);
  return *end == 0;
}

void ScheduleRelease(bool mouse, int code, long ms) {
  Release r;
  r.due = GetTickCount() + (DWORD)(ms < 1 ? 1 : ms);
  r.mouse = mouse;
  r.code = code;
  g_releases.push_back(r);
}

} // namespace

// Startup (startPlugin, before the other hooks): input_isolation.flag in the
// mod folder = start with isolation on (kenshi-ctl launch writes it; the
// harness deletes it here, so a later manual launch starts normal). Hooks are
// installed when the harness is enabled or isolation starts on.
void InputIsolationStartup() {
  Lock();
  Unlock();
  WriteMarker(false);
  const std::string flag = HarnessDir() + "\\input_isolation.flag";
  const bool startOn = FileExists(flag);
  if (startOn)
    DeleteFileA(flag.c_str());
  if (HarnessEnabled() || startOn)
    EnsureHooks();
  if (startOn)
    SetIsolation(true, "input_isolation.flag at startup");
}

bool InputIsolationOn() { return g_on != 0; }

// Every frame (game thread): attach to the game window, release timed key /
// button presses.
void InputIsolationTick() {
  ++g_frames;
  if (g_hooksTried && !g_prevProc)
    AttachWindow();
  if (g_releases.empty())
    return;
  DWORD now = GetTickCount();
  Lock();
  for (size_t i = 0; i < g_releases.size();) {
    if ((LONG)(now - g_releases[i].due) >= 0) {
      if (g_on) {
        if (g_releases[i].mouse)
          ButtonEvent(g_releases[i].code, false);
        else
          KeyEvent(g_releases[i].code, false);
      }
      g_releases.erase(g_releases.begin() + i);
    } else {
      ++i;
    }
  }
  Unlock();
}

// input_isolation on|off|status, key_inject, mouse_inject (any phase).
bool RunInputCommand(const std::vector<std::string> &f, bool &ok, std::string &out) {
  const std::string cmd = Lower(f[1]);
  if (cmd == "input_isolation") {
    const std::string sub = f.size() >= 3 ? Lower(f[2]) : "status";
    if (sub == "on") {
      EnsureHooks();
      AttachWindow();
      SetIsolation(true, "command");
    } else if (sub == "off") {
      SetIsolation(false, "command");
    } else if (sub != "status") {
      out = "usage: input_isolation on|off|status";
      return true;
    }
    ok = true;
    out = Status();
    return true;
  }
  if (cmd != "key_inject" && cmd != "mouse_inject")
    return false;
  if (!g_on) {
    out = "input isolation is off (input_isolation on first; injected input only feeds the isolated game)";
    return true;
  }
  if (cmd == "key_inject") { // key_inject <key> [down|up|tap] [ms]
    int vk = 0;
    if (f.size() < 3 || !inject::ParseKeyName(f[2], vk)) {
      out = "usage: key_inject <key: 0xVK | a..z | 0..9 | f1..f12 | esc | space | enter | shift | ctrl | alt | "
            "ralt | backslash | ; ' [ ] ...> [down|up|tap] [ms (tap hold, default 120)]";
      return true;
    }
    const std::string how = f.size() >= 4 ? Lower(f[3]) : "tap";
    long ms = 120;
    if (f.size() >= 5 && !ParseInt(f[4], ms)) {
      out = "bad ms: " + f[4];
      return true;
    }
    if (how != "down" && how != "up" && how != "tap") {
      out = "key_inject: down|up|tap";
      return true;
    }
    Lock();
    KeyEvent(vk, how != "up");
    if (how == "tap")
      ScheduleRelease(false, vk, ms);
    int kbd = CountDevices(kDevKeyboard);
    Unlock();
    ok = true;
    out = "key " + Hex((unsigned long long)vk) + " dik=" +
          Hex((unsigned long long)inject::VkToDik(vk, (int)MapVirtualKeyA((UINT)vk, 0))) + " " + how +
          (how == "tap" ? " " + Int(ms) + "ms" : "") + " keyboards=" + Int(kbd);
    return true;
  }
  // mouse_inject <left|right|middle|x1|x2> [down|up|click] [ms] | move <dx> <dy> | at <x> <y> | wheel <delta>
  const std::string what = f.size() >= 3 ? Lower(f[2]) : "";
  int b = 0;
  long a = 0, c = 0;
  Lock();
  if (what == "move" && f.size() >= 5 && ParseInt(f[3], a) && ParseInt(f[4], c)) {
    MoveEvent(a, c, true);
    ok = true;
  } else if (what == "at" && f.size() >= 5 && ParseInt(f[3], a) && ParseInt(f[4], c)) {
    long dx = a - g_virt.x, dy = c - g_virt.y;
    MoveEvent(dx, dy, false);
    g_virt.x = a;
    g_virt.y = c;
    ClampVirt();
    ok = true;
  } else if (what == "wheel" && f.size() >= 4 && ParseInt(f[3], a)) {
    WheelEvent(a);
    ok = true;
  } else if (ParseButton(what, b)) {
    const std::string how = f.size() >= 4 ? Lower(f[3]) : "click";
    long ms = 80;
    if (f.size() >= 5 && !ParseInt(f[4], ms))
      ms = -1;
    if ((how == "down" || how == "up" || how == "click") && ms >= 0) {
      ButtonEvent(b, how != "up");
      if (how == "click")
        ScheduleRelease(true, b, ms);
      ok = true;
    }
  }
  POINT v = g_virt;
  int mice = CountDevices(kDevMouse);
  Unlock();
  out = ok ? "mouse " + what + " cursor=" + Int(v.x) + "," + Int(v.y) + " mice=" + Int(mice)
           : "usage: mouse_inject <left|right|middle|x1|x2> [down|up|click] [ms] | move <dx> <dy> | at <x> <y> "
             "(client px) | wheel <delta (120 = one notch)>";
  return true;
}

extern "C" __declspec(dllexport) int KAH_InputIsolated() { return g_on ? 1 : 0; }
