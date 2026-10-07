// Win32 helpers for the Kenshi test automation (loaded with Add-Type).
using System;
using System.Collections.Generic;
using System.Runtime.InteropServices;
using System.Text;

public static class KenshiWin32 {
  public delegate bool EnumProc(IntPtr hwnd, IntPtr lParam);
  [DllImport("user32.dll")] public static extern bool EnumWindows(EnumProc cb, IntPtr lParam);
  [DllImport("user32.dll")] public static extern bool EnumChildWindows(IntPtr parent, EnumProc cb, IntPtr lParam);
  [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr hwnd, out uint pid);
  [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr hwnd);
  [DllImport("user32.dll", CharSet = CharSet.Unicode)] public static extern int GetClassName(IntPtr hwnd, StringBuilder sb, int max);
  [DllImport("user32.dll", CharSet = CharSet.Unicode)] public static extern int GetWindowText(IntPtr hwnd, StringBuilder sb, int max);
  [DllImport("user32.dll")] public static extern int GetDlgCtrlID(IntPtr hwnd);
  [DllImport("user32.dll")] public static extern IntPtr SendMessage(IntPtr hwnd, uint msg, IntPtr w, IntPtr l);
  [DllImport("user32.dll")] public static extern bool PostMessage(IntPtr hwnd, uint msg, IntPtr w, IntPtr l);
  [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr hwnd, out RECT r);
  [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr hwnd);
  [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow();
  [StructLayout(LayoutKind.Sequential)] public struct RECT { public int Left, Top, Right, Bottom; }

  public const uint WM_COMMAND = 0x0111;
  public const uint BM_CLICK = 0x00F5;

  public class Win {
    public IntPtr Handle; public uint Pid; public string Cls; public string Title; public int Id;
    public override string ToString() {
      return string.Format("0x{0:X} pid={1} id={2} class=[{3}] title=[{4}]", Handle.ToInt64(), Pid, Id, Cls, Title);
    }
  }

  static Win Describe(IntPtr h) {
    var c = new StringBuilder(256); var t = new StringBuilder(512);
    GetClassName(h, c, 256); GetWindowText(h, t, 512);
    uint pid; GetWindowThreadProcessId(h, out pid);
    return new Win { Handle = h, Pid = pid, Cls = c.ToString(), Title = t.ToString(), Id = GetDlgCtrlID(h) };
  }

  // Visible top-level windows owned by any of the given process ids.
  public static List<Win> TopWindows(uint[] pids) {
    var set = new HashSet<uint>(pids); var list = new List<Win>();
    EnumWindows((h, l) => {
      uint pid; GetWindowThreadProcessId(h, out pid);
      if (set.Contains(pid) && IsWindowVisible(h)) list.Add(Describe(h));
      return true;
    }, IntPtr.Zero);
    return list;
  }

  public static List<Win> Children(IntPtr parent) {
    var list = new List<Win>();
    EnumChildWindows(parent, (h, l) => { list.Add(Describe(h)); return true; }, IntPtr.Zero);
    return list;
  }

  [DllImport("user32.dll")] public static extern void keybd_event(byte vk, byte scan, uint flags, UIntPtr extra);
  [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr hwnd, int cmd);
  [DllImport("user32.dll")] public static extern bool IsIconic(IntPtr hwnd);

  // Windows only lets the foreground app hand focus away; a synthetic Alt
  // tap lifts that lock so a background script can focus the game window.
  [DllImport("user32.dll")] public static extern bool AttachThreadInput(uint idAttach, uint idAttachTo, bool attach);
  [DllImport("kernel32.dll")] public static extern uint GetCurrentThreadId();
  [DllImport("user32.dll")] public static extern bool BringWindowToTop(IntPtr hwnd);

  public static bool ForceForeground(IntPtr hwnd) {
    if (IsIconic(hwnd)) ShowWindow(hwnd, 9); // SW_RESTORE
    keybd_event(0x12, 0, 0, UIntPtr.Zero);      // Alt down
    keybd_event(0x12, 0, 2, UIntPtr.Zero);      // Alt up
    if (SetForegroundWindow(hwnd) && GetForegroundWindow() == hwnd) return true;
    // Fallback: share input state with the current foreground thread.
    uint pid;
    uint fgThread = GetWindowThreadProcessId(GetForegroundWindow(), out pid);
    uint me = GetCurrentThreadId();
    AttachThreadInput(me, fgThread, true);
    BringWindowToTop(hwnd);
    SetForegroundWindow(hwnd);
    AttachThreadInput(me, fgThread, false);
    return GetForegroundWindow() == hwnd;
  }

  // Presses a dialog button the way a click would (WM_COMMAND to the dialog).
  public static void PressDialogButton(IntPtr dialog, int id) {
    PostMessage(dialog, WM_COMMAND, new IntPtr(id), IntPtr.Zero);
  }
}

// Background launches: put the game's windows on a chosen monitor without
// activating them, and hand the focus back if the game took it.
public static class KenshiPlace {
  [StructLayout(LayoutKind.Sequential)] public struct RECT { public int Left, Top, Right, Bottom; }
  [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
  public struct MONITORINFOEX {
    public int cbSize; public RECT rcMonitor; public RECT rcWork; public uint dwFlags;
    [MarshalAs(UnmanagedType.ByValTStr, SizeConst = 32)] public string szDevice;
  }
  delegate bool MonitorEnumProc(IntPtr mon, IntPtr hdc, ref RECT r, IntPtr data);
  [DllImport("user32.dll")] static extern bool EnumDisplayMonitors(IntPtr hdc, IntPtr clip, MonitorEnumProc cb, IntPtr data);
  [DllImport("user32.dll", CharSet = CharSet.Unicode)] static extern bool GetMonitorInfo(IntPtr mon, ref MONITORINFOEX mi);
  [DllImport("user32.dll")] static extern IntPtr MonitorFromWindow(IntPtr hwnd, uint flags);
  [DllImport("user32.dll")] static extern IntPtr SetThreadDpiAwarenessContext(IntPtr ctx);
  [DllImport("user32.dll")] static extern bool SetWindowPos(IntPtr hwnd, IntPtr after, int x, int y, int cx, int cy, uint flags);
  [DllImport("user32.dll")] static extern bool GetWindowRect(IntPtr hwnd, out RECT r);
  [DllImport("user32.dll")] static extern bool IsIconic(IntPtr hwnd);
  [DllImport("user32.dll")] static extern bool ShowWindow(IntPtr hwnd, int cmd);
  [DllImport("user32.dll")] static extern IntPtr GetForegroundWindow();
  [DllImport("user32.dll")] static extern bool SetForegroundWindow(IntPtr hwnd);
  [DllImport("user32.dll")] static extern bool IsWindow(IntPtr hwnd);
  [DllImport("user32.dll")] static extern uint GetWindowThreadProcessId(IntPtr hwnd, out uint pid);
  [DllImport("user32.dll")] static extern bool AttachThreadInput(uint a, uint b, bool attach);
  [DllImport("kernel32.dll")] static extern uint GetCurrentThreadId();

  const uint SWP_NOSIZE = 0x1, SWP_NOZORDER = 0x4, SWP_NOACTIVATE = 0x10, SWP_NOOWNERZORDER = 0x200;

  // Physical pixels for everything below (per-monitor DPI aware thread);
  // returns the previous context (IntPtr.Zero before Windows 10 1607).
  static IntPtr PhysicalCoords() {
    try { return SetThreadDpiAwarenessContext(new IntPtr(-4)); } catch (EntryPointNotFoundException) { return IntPtr.Zero; }
  }
  static void Restore(IntPtr ctx) {
    if (ctx == IntPtr.Zero) return;
    try { SetThreadDpiAwarenessContext(ctx); } catch (EntryPointNotFoundException) { }
  }

  static string Norm(string device) {
    device = (device ?? "").Trim();
    return device.StartsWith(@"\\.\") ? device.ToUpperInvariant() : (@"\\.\" + device).ToUpperInvariant();
  }

  static List<MONITORINFOEX> All() {
    var list = new List<MONITORINFOEX>();
    EnumDisplayMonitors(IntPtr.Zero, IntPtr.Zero, (IntPtr m, IntPtr dc, ref RECT r, IntPtr d) => {
      var mi = new MONITORINFOEX(); mi.cbSize = Marshal.SizeOf(typeof(MONITORINFOEX));
      if (GetMonitorInfo(m, ref mi)) list.Add(mi);
      return true;
    }, IntPtr.Zero);
    return list;
  }

  static string Rect(RECT r) { return string.Format("{0},{1} {2}x{3}", r.Left, r.Top, r.Right - r.Left, r.Bottom - r.Top); }

  // "\.\DISPLAY1 0,0 1920x1080 | ..." (physical pixels)
  public static string Monitors() {
    IntPtr ctx = PhysicalCoords();
    try {
      var parts = new List<string>();
      foreach (var m in All()) parts.Add(m.szDevice + " " + Rect(m.rcMonitor) + ((m.dwFlags & 1) != 0 ? " primary" : ""));
      return string.Join(" | ", parts.ToArray());
    } finally { Restore(ctx); }
  }

  // Monitor device the window is (mostly) on, or "none".
  public static string MonitorOf(IntPtr hwnd) {
    IntPtr ctx = PhysicalCoords();
    try {
      IntPtr mon = MonitorFromWindow(hwnd, 0 /* MONITOR_DEFAULTTONULL */);
      if (mon == IntPtr.Zero) return "none";
      var mi = new MONITORINFOEX(); mi.cbSize = Marshal.SizeOf(typeof(MONITORINFOEX));
      return GetMonitorInfo(mon, ref mi) ? mi.szDevice : "?";
    } finally { Restore(ctx); }
  }

  // Moves the window to the monitor's top-left corner without activating it
  // (shrunk to the monitor if bigger; a minimized window is restored without
  // activation first). Returns "" when placed, else the reason.
  public static string Place(IntPtr hwnd, string device, out string where) {
    where = "";
    IntPtr ctx = PhysicalCoords();
    try {
      if (!IsWindow(hwnd)) return "no window";
      string want = Norm(device);
      MONITORINFOEX? hit = null;
      foreach (var m in All()) if (m.szDevice.ToUpperInvariant() == want) hit = m;
      if (hit == null) return "no monitor " + want + " (have: " + Monitors() + ")";
      if (IsIconic(hwnd)) ShowWindow(hwnd, 4 /* SW_SHOWNOACTIVATE */);
      RECT w; GetWindowRect(hwnd, out w);
      RECT mr = hit.Value.rcMonitor;
      int cw = w.Right - w.Left, ch = w.Bottom - w.Top;
      int mw = mr.Right - mr.Left, mh = mr.Bottom - mr.Top;
      uint flags = SWP_NOZORDER | SWP_NOACTIVATE | SWP_NOOWNERZORDER;
      bool shrink = cw > mw || ch > mh;
      if (!shrink) flags |= SWP_NOSIZE;
      if (w.Left != mr.Left || w.Top != mr.Top || shrink)
        SetWindowPos(hwnd, IntPtr.Zero, mr.Left, mr.Top, Math.Min(cw, mw), Math.Min(ch, mh), flags);
      GetWindowRect(hwnd, out w);
      where = want + " window " + Rect(w) + " monitor " + Rect(mr) + (shrink ? " (shrunk to the monitor)" : "");
      return "";
    } finally { Restore(ctx); }
  }

  public static bool IsOwnedBy(IntPtr hwnd, uint[] pids) {
    uint pid; GetWindowThreadProcessId(hwnd, out pid);
    return Array.IndexOf(pids, pid) >= 0;
  }

  // The foreground window now, if it belongs to one of pids (else IntPtr.Zero).
  public static IntPtr ForegroundOf(uint[] pids) {
    IntPtr fg = GetForegroundWindow();
    return fg != IntPtr.Zero && IsOwnedBy(fg, pids) ? fg : IntPtr.Zero;
  }

  // Gives the foreground back to prev (the user's window before the launch)
  // while the game holds it: attach to the game's input thread, which may
  // hand the foreground on. Never activates the game.
  public static bool GiveBack(IntPtr prev) {
    if (prev == IntPtr.Zero || !IsWindow(prev)) return false;
    IntPtr fg = GetForegroundWindow();
    if (fg == prev) return true;
    uint pid;
    uint fgThread = GetWindowThreadProcessId(fg, out pid), me = GetCurrentThreadId();
    bool attached = fgThread != 0 && AttachThreadInput(me, fgThread, true);
    SetForegroundWindow(prev);
    if (attached) AttachThreadInput(me, fgThread, false);
    return GetForegroundWindow() == prev;
  }

  public static IntPtr Foreground() { return GetForegroundWindow(); }
}
