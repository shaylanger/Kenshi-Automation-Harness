// Offline test of the fps accumulator (src/FrameStats.h).
// Build and run: tests\run_tests.bat
#include "FrameStats.h"

#include <cmath>

int g_failed = 0;
void Check(bool cond, const char *what) {
  printf("%s %s\n", cond ? "PASS" : "FAIL", what);
  if (!cond)
    ++g_failed;
}
bool Near(double a, double b) { return fabs(a - b) < 1e-6; }

int main() {
  FrameStats s;
  Check(s.frames == 0 && s.AverageFps() == 0.0 && s.MinFps() == 0.0, "empty: zeros");
  Check(s.Report() == "avg=0.0 min=0.0 worst_ms=0.0 frames=0 seconds=0.0", "empty report");

  for (int i = 0; i < 59; ++i)
    s.Add(1.0 / 60.0);
  s.Add(0.05); // one 50 ms hitch
  Check(s.frames == 60, "60 frames counted");
  Check(Near(s.seconds, 59.0 / 60.0 + 0.05), "seconds = sum of deltas");
  Check(Near(s.AverageFps(), 60.0 / (59.0 / 60.0 + 0.05)), "average = frames / seconds");
  Check(Near(s.MinFps(), 20.0), "min fps from the worst frame");
  Check(s.Report() == "avg=58.1 min=20.0 worst_ms=50.0 frames=60 seconds=1.0", "report format");

  s.Add(0.0);
  s.Add(-1.0);
  s.Add(7200.0);
  Check(s.frames == 60, "zero, negative and huge deltas ignored");

  s.Reset();
  Check(s.frames == 0 && s.seconds == 0.0 && s.worstSec == 0.0, "reset clears the window");
  s.Add(0.02);
  Check(Near(s.AverageFps(), 50.0) && Near(s.MinFps(), 50.0), "new window after reset");

  printf(g_failed ? "%d FAILED\n" : "all fps tests passed\n", g_failed);
  return g_failed ? 1 : 0;
}
