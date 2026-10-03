// Screenshot of one window, also when it is behind other windows
// (PrintWindow with PW_RENDERFULLCONTENT works for D3D11 windows on Windows 10).
using System;
using System.Drawing;
using System.Drawing.Imaging;
using System.Runtime.InteropServices;

public static class KenshiCapture {
  [DllImport("user32.dll")] static extern bool PrintWindow(IntPtr hwnd, IntPtr hdc, uint flags);
  [DllImport("user32.dll")] static extern bool GetClientRect(IntPtr hwnd, out RECT r);
  [StructLayout(LayoutKind.Sequential)] struct RECT { public int Left, Top, Right, Bottom; }

  // Saves a PNG scaled to at most maxWidth pixels wide; returns "w x h".
  public static string Save(IntPtr hwnd, string path, int maxWidth) {
    RECT r;
    GetClientRect(hwnd, out r);
    int w = Math.Max(1, r.Right - r.Left), h = Math.Max(1, r.Bottom - r.Top);
    using (var bmp = new Bitmap(w, h, PixelFormat.Format32bppArgb)) {
      using (var g = Graphics.FromImage(bmp)) {
        IntPtr hdc = g.GetHdc();
        PrintWindow(hwnd, hdc, 1 | 2); // PW_CLIENTONLY | PW_RENDERFULLCONTENT
        g.ReleaseHdc(hdc);
      }
      int ow = Math.Min(w, maxWidth), oh = (int)((long)h * ow / w);
      using (var scaled = new Bitmap(bmp, ow, oh)) scaled.Save(path, ImageFormat.Png);
      return ow + "x" + oh;
    }
  }
}
