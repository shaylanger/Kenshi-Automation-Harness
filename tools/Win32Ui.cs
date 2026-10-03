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
