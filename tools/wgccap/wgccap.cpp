// wgccap.exe: occlusion-proof capture of one window's client area with Windows Graphics Capture (GPU), streamed as raw
// BGRA frames at a fixed frame rate into a named pipe that ffmpeg reads (-f rawvideo -pix_fmt bgra -video_size WxH
// -framerate F -i \\.\pipe\<name>). Built for take recording (capture-fix 2026-10-11): ffmpeg gdigrab films the SCREEN
// area of the window, so anything covering the background game window was recorded; WGC reads the window's own
// composition surface (works covered, on any monitor, never focuses or touches the window).
//
//   wgccap.exe --title "<exact window title>" [--hwnd 0x..] [--fps 30000/1001] [--pipe \\.\pipe\name] [--max-sec 3600]
//              [--connect-sec 30] [--probe]
// stdout: "READY <w>x<h> fps=<f> pipe=<name>" once the first frame arrived and the pipe exists (then it waits for the
// reader), or "ERROR <why>" (exit 2). --probe prints "SIZE <w>x<h>" and exits after the first frame.
// Frame n of the stream is the newest captured frame at t0 + n/fps (t0 = reader connected): a frame the game did not
// present in time is repeated, so the video length always equals wall time (same as gdigrab's pacing).
// Exits 0 when the reader closes the pipe (ffmpeg 'q' / -t / killed), 3 when the window is gone, 4 at --max-sec.
#include <windows.h>
#include <d3d11_4.h>
#include <dxgi.h>
#include <dwmapi.h>
#include <timeapi.h>
#include <inspectable.h>
#include <winrt/Windows.Foundation.h>
#include <winrt/Windows.Graphics.h>
#include <winrt/Windows.Graphics.Capture.h>
#include <winrt/Windows.Graphics.DirectX.h>
#include <winrt/Windows.Graphics.DirectX.Direct3D11.h>
#include <windows.graphics.capture.interop.h>
#include <windows.graphics.directx.direct3d11.interop.h>
#include <algorithm>
#include <atomic>
#include <string>
#include <vector>
#include <cstdio>
#pragma comment(lib, "d3d11.lib")
#pragma comment(lib, "dxgi.lib")
#pragma comment(lib, "dwmapi.lib")
#pragma comment(lib, "windowsapp.lib")
#pragma comment(lib, "winmm.lib")
#pragma comment(lib, "user32.lib")

namespace wgc = winrt::Windows::Graphics::Capture;
namespace wd3d = winrt::Windows::Graphics::DirectX::Direct3D11;

static void out(const char* fmt, ...) {
  va_list a; va_start(a, fmt); vfprintf(stdout, fmt, a); va_end(a); fputc('\n', stdout); fflush(stdout);
}
static int fail(const char* why) { out("ERROR %s", why); return 2; }

struct Cap {
  HWND hwnd = nullptr;
  winrt::com_ptr<ID3D11Device> dev;
  winrt::com_ptr<ID3D11DeviceContext> ctx;
  winrt::com_ptr<ID3D11Texture2D> latest;   // client-area copy, size W x H
  winrt::com_ptr<ID3D11Texture2D> staging;
  std::atomic<int> frames{0};
  std::atomic<bool> gone{false};
  int W = 0, H = 0;
  winrt::Windows::Graphics::SizeInt32 poolSize{0, 0};
  wd3d::IDirect3DDevice rtDev{nullptr};
  wgc::Direct3D11CaptureFramePool pool{nullptr};
  wgc::GraphicsCaptureSession session{nullptr};

  // client rect origin inside the captured frame (WGC frame = DWM extended frame bounds), physical pixels
  bool clientOffset(int& ox, int& oy) {
    RECT fb; POINT p{0, 0};
    if (FAILED(DwmGetWindowAttribute(hwnd, DWMWA_EXTENDED_FRAME_BOUNDS, &fb, sizeof fb))) return false;
    if (!ClientToScreen(hwnd, &p)) return false;
    ox = p.x - fb.left; oy = p.y - fb.top; if (ox < 0) ox = 0; if (oy < 0) oy = 0;
    return true;
  }
  // one thread does everything (poll + copy + map): the WGC pool uses this device's context too, a FrameArrived callback
  // on the pool's thread deadlocked against the writer's CopyResource/Map (2026-10-11)
  bool poll() {
    wgc::Direct3D11CaptureFrame f{nullptr};
    for (;;) { auto g = pool.TryGetNextFrame(); if (!g) break; if (f) f.Close(); f = g; }   // newest frame only
    if (!f) return false;
    auto cs = f.ContentSize();
    auto access = f.Surface().as<::Windows::Graphics::DirectX::Direct3D11::IDirect3DDxgiInterfaceAccess>();
    winrt::com_ptr<ID3D11Texture2D> src;
    winrt::check_hresult(access->GetInterface(__uuidof(ID3D11Texture2D), src.put_void()));
    D3D11_TEXTURE2D_DESC sd; src->GetDesc(&sd);
    int ox = 0, oy = 0; clientOffset(ox, oy);
    D3D11_BOX b; b.left = ox; b.top = oy; b.front = 0; b.back = 1;
    b.right = (UINT)std::min((int)sd.Width, std::min(cs.Width, ox + W)); b.bottom = (UINT)std::min((int)sd.Height, std::min(cs.Height, oy + H));
    if (b.right > b.left && b.bottom > b.top) {
      ctx->CopySubresourceRegion(latest.get(), 0, 0, 0, 0, src.get(), 0, &b);
      frames++;
    }
    f.Close();
    if (cs.Width != poolSize.Width || cs.Height != poolSize.Height) {   // window resized: new pool size
      poolSize = cs; pool.Recreate(rtDev, winrt::Windows::Graphics::DirectX::DirectXPixelFormat::B8G8R8A8UIntNormalized, 3, cs);
    }
    return true;
  }
};

static HWND findWin(const std::wstring& title) {
  HWND h = FindWindowW(nullptr, title.c_str());   // exact title, like gdigrab title=
  return h;
}
static std::wstring widen(const char* s) {
  int n = MultiByteToWideChar(CP_UTF8, 0, s, -1, nullptr, 0); std::wstring w(n ? n - 1 : 0, L'\0');
  if (n) MultiByteToWideChar(CP_UTF8, 0, s, -1, &w[0], n); return w;
}
static bool parseFps(const char* s, double& fps) {
  if (!strcmp(s, "ntsc")) { fps = 30000.0 / 1001.0; return true; }
  if (!strcmp(s, "pal")) { fps = 25.0; return true; }
  double a = 0, b = 1; if (sscanf_s(s, "%lf/%lf", &a, &b) >= 1 && a > 0 && b > 0) { fps = a / b; return true; }
  return false;
}

int main(int argc, char** argv) {
  std::wstring title; HWND hwnd = nullptr; double fps = 30000.0 / 1001.0; std::string fpsStr = "30000/1001";
  std::string pipeName; double maxSec = 3600, connectSec = 30; bool probe = false;
  for (int i = 1; i < argc; i++) {
    std::string a = argv[i]; auto nxt = [&]() -> const char* { return i + 1 < argc ? argv[++i] : ""; };
    if (a == "--title") title = widen(nxt());
    else if (a == "--hwnd") hwnd = (HWND)(uintptr_t)strtoull(nxt(), nullptr, 0);
    else if (a == "--fps") { fpsStr = nxt(); if (!parseFps(fpsStr.c_str(), fps)) return fail("bad --fps"); }
    else if (a == "--pipe") pipeName = nxt();
    else if (a == "--max-sec") maxSec = atof(nxt());
    else if (a == "--connect-sec") connectSec = atof(nxt());
    else if (a == "--probe") probe = true;
    else { fprintf(stderr, "unknown arg %s\n", a.c_str()); return fail("usage: --title <t> [--fps f] [--pipe name] [--probe]"); }
  }
  SetProcessDpiAwarenessContext(DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2);   // physical pixels, like gdigrab
  if (!hwnd && !title.empty()) hwnd = findWin(title);
  if (!hwnd || !IsWindow(hwnd)) return fail("window not found");
  if (IsIconic(hwnd)) return fail("window minimized (WGC gets no frames)");
  if (!wgc::GraphicsCaptureSession::IsSupported()) return fail("Windows Graphics Capture not supported here");
  if (pipeName.empty()) { char b[64]; sprintf_s(b, "\\\\.\\pipe\\wgccap-%lu", GetCurrentProcessId()); pipeName = b; }

  winrt::init_apartment(winrt::apartment_type::multi_threaded);
  Cap c; c.hwnd = hwnd;
  RECT cr; GetClientRect(hwnd, &cr); c.W = cr.right - cr.left; c.H = cr.bottom - cr.top;
  c.W &= ~1; c.H &= ~1;   // even size (yuv420p encoders)
  if (c.W < 2 || c.H < 2) return fail("empty client rect");

  D3D_FEATURE_LEVEL fl;
  HRESULT hr = D3D11CreateDevice(nullptr, D3D_DRIVER_TYPE_HARDWARE, nullptr, D3D11_CREATE_DEVICE_BGRA_SUPPORT, nullptr, 0,
                                 D3D11_SDK_VERSION, c.dev.put(), &fl, c.ctx.put());
  if (FAILED(hr)) return fail("D3D11CreateDevice failed");
  // the WGC frame pool uses this device's immediate context on its own thread: D3D multithread protection is required
  // (without it the writer's CopyResource and the pool deadlocked after the first frame)
  if (auto mt = c.ctx.try_as<ID3D11Multithread>()) mt->SetMultithreadProtected(TRUE);
  D3D11_TEXTURE2D_DESC td{}; td.Width = c.W; td.Height = c.H; td.MipLevels = 1; td.ArraySize = 1;
  td.Format = DXGI_FORMAT_B8G8R8A8_UNORM; td.SampleDesc.Count = 1; td.Usage = D3D11_USAGE_DEFAULT;
  if (FAILED(c.dev->CreateTexture2D(&td, nullptr, c.latest.put()))) return fail("texture");
  td.Usage = D3D11_USAGE_STAGING; td.CPUAccessFlags = D3D11_CPU_ACCESS_READ;
  if (FAILED(c.dev->CreateTexture2D(&td, nullptr, c.staging.put()))) return fail("staging texture");

  try {
    auto dxgi = c.dev.as<IDXGIDevice>();
    winrt::com_ptr<::IInspectable> insp;
    winrt::check_hresult(CreateDirect3D11DeviceFromDXGIDevice(dxgi.get(), insp.put()));
    c.rtDev = insp.as<wd3d::IDirect3DDevice>();
    auto interop = winrt::get_activation_factory<wgc::GraphicsCaptureItem, IGraphicsCaptureItemInterop>();
    wgc::GraphicsCaptureItem item{nullptr};
    winrt::check_hresult(interop->CreateForWindow(hwnd, winrt::guid_of<wgc::GraphicsCaptureItem>(), winrt::put_abi(item)));
    c.poolSize = item.Size();
    c.pool = wgc::Direct3D11CaptureFramePool::CreateFreeThreaded(
        c.rtDev, winrt::Windows::Graphics::DirectX::DirectXPixelFormat::B8G8R8A8UIntNormalized, 3, c.poolSize);
    item.Closed([&c](auto const&, auto const&) { c.gone = true; });
    c.session = c.pool.CreateCaptureSession(item);
    try { c.session.IsCursorCaptureEnabled(false); } catch (...) {}   // Windows 10 2004+ (gdigrab -draw_mouse 0)
    c.session.StartCapture();
  } catch (winrt::hresult_error const& e) {
    std::string m = winrt::to_string(e.message()); char b[512]; sprintf_s(b, "capture start: 0x%08x %s", (unsigned)e.code(), m.c_str());
    return fail(b);
  }
  for (int i = 0; i < 300 && c.frames == 0; i++) { try { c.poll(); } catch (...) {} if (!c.frames) Sleep(10); }   // first frame (<= 3 s)
  if (c.frames == 0) return fail("no frame from the window in 3 s");
  if (probe) { out("SIZE %dx%d", c.W, c.H); c.session.Close(); c.pool.Close(); return 0; }

  std::wstring wpipe = widen(pipeName.c_str());
  DWORD fsz = (DWORD)c.W * c.H * 4;
  HANDLE pipe = CreateNamedPipeW(wpipe.c_str(), PIPE_ACCESS_OUTBOUND | FILE_FLAG_OVERLAPPED | FILE_FLAG_FIRST_PIPE_INSTANCE,
                                 PIPE_TYPE_BYTE | PIPE_WAIT | PIPE_REJECT_REMOTE_CLIENTS, 1, fsz * 2, 0, 0, nullptr);
  if (pipe == INVALID_HANDLE_VALUE) return fail("CreateNamedPipe failed (name in use?)");
  out("READY %dx%d fps=%s pipe=%s", c.W, c.H, fpsStr.c_str(), pipeName.c_str());

  OVERLAPPED ov{}; ov.hEvent = CreateEventW(nullptr, TRUE, FALSE, nullptr);
  if (!ConnectNamedPipe(pipe, &ov)) {
    DWORD e = GetLastError();
    if (e == ERROR_IO_PENDING) {
      if (WaitForSingleObject(ov.hEvent, (DWORD)(connectSec * 1000)) != WAIT_OBJECT_0) { CancelIo(pipe); return fail("reader never connected"); }
    } else if (e != ERROR_PIPE_CONNECTED) return fail("ConnectNamedPipe failed");
  }
  bool dbg = getenv("WGCCAP_DEBUG") != nullptr;
  if (dbg) fprintf(stderr, "connected\n");
  timeBeginPeriod(1);
  std::vector<unsigned char> buf(fsz);
  LARGE_INTEGER qf, t0, now; QueryPerformanceFrequency(&qf); QueryPerformanceCounter(&t0);
  int rc = 0; long long n = 0; long long maxN = (long long)(maxSec * fps);
  for (;; n++) {
    if (n >= maxN) { rc = 4; break; }
    if (c.gone || !IsWindow(hwnd)) { rc = 3; break; }
    if (dbg && n < 10) fprintf(stderr, "tick %lld start frames=%d\n", n, (int)c.frames);
    double due = n / fps;
    for (;;) {
      QueryPerformanceCounter(&now); double t = double(now.QuadPart - t0.QuadPart) / qf.QuadPart;
      if (t >= due) break;
      double ms = (due - t) * 1000.0; Sleep(ms > 2 ? (DWORD)(ms - 1) : 0);
    }
    try { c.poll(); } catch (...) {}
    {
      c.ctx->CopyResource(c.staging.get(), c.latest.get());
      D3D11_MAPPED_SUBRESOURCE ms; HRESULT mh = c.ctx->Map(c.staging.get(), 0, D3D11_MAP_READ, 0, &ms);
      if (FAILED(mh)) { fprintf(stderr, "wgccap: map failed 0x%08x\n", (unsigned)mh); rc = 5; break; }
      for (int y = 0; y < c.H; y++) memcpy(&buf[(size_t)y * c.W * 4], (unsigned char*)ms.pData + (size_t)y * ms.RowPitch, (size_t)c.W * 4);
      c.ctx->Unmap(c.staging.get(), 0);
    }
    if (dbg && n < 10) fprintf(stderr, "tick %lld write\n", n);
    DWORD done = 0; size_t off = 0; bool ok = true;
    while (off < buf.size()) {
      OVERLAPPED wo{}; wo.hEvent = ov.hEvent; ResetEvent(ov.hEvent);
      DWORD chunk = (DWORD)std::min<size_t>(buf.size() - off, 1 << 20);
      if (!WriteFile(pipe, &buf[off], chunk, nullptr, &wo) && GetLastError() != ERROR_IO_PENDING) { ok = false; break; }
      if (!GetOverlappedResult(pipe, &wo, &done, TRUE)) { ok = false; break; }
      off += done;
    }
    if (dbg && (n < 10 || n % 30 == 0)) fprintf(stderr, "tick %lld done ok=%d err=%lu\n", n, (int)ok, ok ? 0 : GetLastError());
    if (!ok) { rc = 0; break; }   // reader closed the pipe: normal end
  }
  timeEndPeriod(1);
  FlushFileBuffers(pipe); DisconnectNamedPipe(pipe); CloseHandle(pipe);
  try { c.session.Close(); c.pool.Close(); } catch (...) {}
  fprintf(stderr, "wgccap: %lld frames written, %d captured, rc=%d\n", n, (int)c.frames, rc);
  return rc;
}
