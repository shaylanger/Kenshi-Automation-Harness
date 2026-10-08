<#
kenshi-ctl.ps1: start, stop and watch Kenshi for automated test runs.

  kenshi-ctl.ps1 status                 running? pid, uptime, window, launcher open?
  kenshi-ctl.ps1 launch [-Save <name>]  archive logs, start Kenshi, press the launcher's OK,
                                        wait for the harness (and load <name> if given)
  kenshi-ctl.ps1 stop                   kill Kenshi (never saves)
  kenshi-ctl.ps1 restart [-Save <name>] stop + launch
  kenshi-ctl.ps1 health                 ok | crashed | hung | not-running (exit code 0/1)
  kenshi-ctl.ps1 monitors               monitor device names and bounds (physical pixels)
  kenshi-ctl.ps1 place -Monitor <DISPLAYn>  move the game window there without activating it
  kenshi-ctl.ps1 window                 which monitor the game window is on + who has the foreground
  launch/restart options for runs while someone uses the PC: -Monitor <DISPLAYn> -Background -Isolate
                                        (see the param block)
  kenshi-ctl.ps1 focus                  bring the game window to the foreground (KenshiFP
                                        hides the cursor and takes input only when focused)
  kenshi-ctl.ps1 screenshot [-Save n]   PNG of the game window (works in the background)
                                        -> <ArchiveRoot>\shots\<n|time>.png

Options: -Kenshi <game folder> (default: $env:KENSHI_DIR, else the Steam default),
-ArchiveRoot <folder> (default C:\KenshiTestRuns), -ExtraLogs <files> (other mods'
logs to archive before each launch, e.g. because they reset on launch).

Steam must be running (steam_appid.txt next to kenshi_x64.exe lets the exe
start without Steam's launch prompt). With RE_Kenshi the game restarts into
RE_Kenshi\kenshi_x64.exe --norestart; the launcher dialog opens in that second
process, so both are followed. Loading a save needs the harness enabled
(kah on, i.e. mods\AutomationHarness\enabled.flag).
#>
param(
  [Parameter(Position = 0)][string]$Command = 'status',
  [string]$Save = '',
  [int]$TimeoutSec = 300,
  [string]$Kenshi = $(if ($env:KENSHI_DIR) { $env:KENSHI_DIR } else { 'C:\Program Files (x86)\Steam\steamapps\common\Kenshi' }),
  [string]$ArchiveRoot = 'C:\KenshiTestRuns',
  [string[]]$ExtraLogs = @(),
  # launch/restart for automated runs while someone uses the PC:
  #  -Monitor DISPLAY1  put the launcher and game windows on that monitor (device name, see `monitors`), never activated
  #  -Background        keep the user's foreground window: if the game takes the focus during the launch, hand it back
  #  -Isolate           start with harness input isolation on (mods\AutomationHarness\input_isolation.flag, read and
  #                     deleted by the harness at startup): the game ignores real keys/mouse, never clips the cursor,
  #                     takes key_inject/mouse_inject input and keeps running unfocused
  [string]$Monitor = '',
  [switch]$Background,
  [switch]$Isolate
)
$ErrorActionPreference = 'Stop'
Add-Type -Path (Join-Path $PSScriptRoot 'Win32Ui.cs')

$HarnessDir = "$Kenshi\mods\AutomationHarness"
$HarnessLog = "$HarnessDir\harness.log"
$LogArchive = Join-Path $ArchiveRoot 'logs'
$LauncherOkId = 1003

if (-not (Test-Path "$Kenshi\kenshi_x64.exe")) { throw "no kenshi_x64.exe in $Kenshi (use -Kenshi or KENSHI_DIR)" }

# The leading comma keeps a one-process result an array (so .Count works).
function Get-KenshiProcs { , @(Get-CimInstance Win32_Process -Filter "Name='kenshi_x64.exe'") }

function Get-Launcher {
  $procs = Get-KenshiProcs
  if ($procs.Count -eq 0) { return $null }
  $pids = [uint32[]]@($procs | ForEach-Object { [uint32]$_.ProcessId })
  [KenshiWin32]::TopWindows($pids) | Where-Object { $_.Cls -eq '#32770' -and $_.Title -like 'Kenshi*' } | Select-Object -First 1
}

function Get-GameWindow {
  $procs = Get-KenshiProcs
  if ($procs.Count -eq 0) { return $null }
  $pids = [uint32[]]@($procs | ForEach-Object { [uint32]$_.ProcessId })
  [KenshiWin32]::TopWindows($pids) | Where-Object { $_.Cls -like 'OgreD3D*' } | Select-Object -First 1
}

function Get-LatestCrashDump {
  Get-ChildItem $Kenshi -Filter 'crashDump*.zip' -ErrorAction SilentlyContinue |
    Sort-Object LastWriteTime -Descending | Select-Object -First 1
}

function Save-Logs([string]$Reason) {
  $stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
  $dest = Join-Path $LogArchive "$stamp-$Reason"
  New-Item -ItemType Directory -Force $dest | Out-Null
  foreach ($f in @($HarnessLog, "$HarnessDir\outbox.txt", "$Kenshi\RE_Kenshi_log.txt") + $ExtraLogs) {
    if (Test-Path $f) { Copy-Item $f $dest -ErrorAction SilentlyContinue }
  }
  $dest
}

function Stop-Kenshi {
  $procs = Get-KenshiProcs
  foreach ($p in $procs) { Stop-Process -Id $p.ProcessId -Force -ErrorAction SilentlyContinue }
  $deadline = (Get-Date).AddSeconds(30)
  while ((Get-KenshiProcs).Count -gt 0 -and (Get-Date) -lt $deadline) { Start-Sleep -Milliseconds 500 }
  if ((Get-KenshiProcs).Count -gt 0) { throw 'Kenshi did not exit' }
  "stopped ($($procs.Count) process(es))"
}

function Wait-Until([scriptblock]$Cond, [int]$Seconds, [string]$What) {
  $deadline = (Get-Date).AddSeconds($Seconds)
  while ((Get-Date) -lt $deadline) {
    # background launch: place new windows / hand the focus back before (and between) checks
    if ($script:LaunchKeeper) { & $script:LaunchKeeper }
    $r = & $Cond
    if ($r) { return $r }
    if ((Get-KenshiProcs).Count -eq 0) { throw "Kenshi exited while waiting for $What" }
    Start-Sleep -Milliseconds $(if ($script:LaunchKeeper) { 100 } else { 500 })
  }
  throw "timed out after $Seconds s waiting for $What"
}

function Read-HarnessLogMatch([string]$Pattern) {
  if (-not (Test-Path $HarnessLog)) { return $null }
  Select-String -Path $HarnessLog -Pattern $Pattern -SimpleMatch | Select-Object -Last 1
}

function Start-Kenshi {
  if ((Get-KenshiProcs).Count -gt 0) { throw 'Kenshi is already running (stop it first)' }
  if (-not (Get-Process steam -ErrorAction SilentlyContinue)) { throw 'Steam is not running' }
  if (-not (Test-Path "$HarnessDir\AutomationHarness.dll")) { throw "harness not installed in $HarnessDir" }
  $archived = Save-Logs 'before-launch'
  "logs archived to $archived"
  # The harness recreates harness.log on start; removing it keeps the waits
  # below from matching lines of the previous session.
  Remove-Item $HarnessLog -ErrorAction SilentlyContinue
  if ($Save) {
    if (-not (Test-Path "$HarnessDir\enabled.flag")) { throw 'harness is off (kah on) so autoload would be ignored' }
    Set-Content -Path "$HarnessDir\autoload.txt" -Value $Save -Encoding Ascii -NoNewline
  }
  Remove-Item "$HarnessDir\inbox.txt", "$HarnessDir\inbox.txt.lock", "$HarnessDir\inbox.txt.reading" -ErrorAction SilentlyContinue
  $flag = "$HarnessDir\input_isolation.flag"
  if ($Isolate) { Set-Content -Path $flag -Value 'kenshi-ctl launch -Isolate' -Encoding Ascii }
  else { Remove-Item $flag -ErrorAction SilentlyContinue }
  $script:PrevForeground = [KenshiPlace]::Foreground()
  $script:KeeperNotes = @{}
  $script:FocusReturns = 0
  if ($Monitor -or $Background) { $script:LaunchKeeper = { Keep-Background } }
  $t0 = Get-Date
  Start-Process -FilePath "$Kenshi\kenshi_x64.exe" -WorkingDirectory $Kenshi | Out-Null
  $launcher = Wait-Until { Get-Launcher } 120 'the launcher dialog'
  # Let the dialog finish initialising (mod list) before pressing OK.
  Start-Sleep -Seconds 2
  [KenshiWin32]::PressDialogButton($launcher.Handle, $LauncherOkId)
  "launcher OK pressed after $([int]((Get-Date) - $t0).TotalSeconds) s"
  Wait-Until { -not (Get-Launcher) -and (Get-GameWindow) } 60 'the game window' | Out-Null
  Wait-Until { Read-HarnessLogMatch 'KAH: frame listener running' } $TimeoutSec 'the harness frame listener' | Out-Null
  "frame listener running after $([int]((Get-Date) - $t0).TotalSeconds) s"
  if ($Save) {
    Wait-Until { Read-HarnessLogMatch "KAH: autoload $Save" } $TimeoutSec 'autoload' | ForEach-Object { $_.Line }
  }
  $p = Get-KenshiProcs | Select-Object -First 1
  "running: pid=$($p.ProcessId) cmd=$($p.CommandLine)"
  if ($script:LaunchKeeper) {
    & $script:LaunchKeeper
    $script:LaunchKeeper = $null
    foreach ($n in $script:KeeperNotes.Values) { "background: $n" }
    "background: focus handed back $($script:FocusReturns) time(s); foreground now: $(Get-ForegroundDesc)"
  }
  if ($Isolate) { "input isolation: starts ON (input_isolation.flag); check with: kah input_isolation status" }
}

function Get-ForegroundDesc {
  $fg = [KenshiPlace]::Foreground(); $fgPid = [uint32]0
  [KenshiWin32]::GetWindowThreadProcessId($fg, [ref]$fgPid) | Out-Null
  $name = if ($fgPid) { (Get-Process -Id $fgPid -ErrorAction SilentlyContinue).ProcessName } else { 'none' }
  "$name (pid $fgPid)"
}

# Background launch keeper (each wait poll): every visible window of the game
# processes goes to -Monitor without activation; with -Background, if a game
# window took the foreground, it goes back to the window that had it before.
function Keep-Background {
  $pids = [uint32[]]@(Get-Process kenshi_x64 -ErrorAction SilentlyContinue | ForEach-Object { [uint32]$_.Id })
  if ($pids.Count -eq 0) { return }
  if ($Monitor) {
    foreach ($w in [KenshiWin32]::TopWindows($pids)) {
      $where = ''
      $err = [KenshiPlace]::Place($w.Handle, $Monitor, [ref]$where)
      $script:KeeperNotes["$($w.Handle)"] = if ($err) { "$($w.Cls): not placed: $err" } else { "$($w.Cls) on $where" }
    }
  }
  if ($Background -and [KenshiPlace]::ForegroundOf($pids) -ne [IntPtr]::Zero) {
    if ([KenshiPlace]::GiveBack($script:PrevForeground)) { $script:FocusReturns++ }
    # nothing to give it back to (launched from a background shell, user idle): drop it instead
    elseif ([KenshiPlace]::Demote([KenshiPlace]::ForegroundOf($pids))) { $script:FocusReturns++; $script:KeeperNotes['demote'] = 'game had the foreground with no window to hand it to: minimized/restored to drop it' }
  }
}

# background: re-place the game window (if -Monitor) and make sure it does not hold the foreground; prints `window`
function Keep-BackgroundNow {
  $win = Get-GameWindow
  if (-not $win) { throw 'no game window' }
  if ($Monitor) { $where = ''; [KenshiPlace]::Place($win.Handle, $Monitor, [ref]$where) | Out-Null }
  $pids = [uint32[]]@(Get-Process kenshi_x64 -ErrorAction SilentlyContinue | ForEach-Object { [uint32]$_.Id })
  $note = ''
  if ([KenshiPlace]::ForegroundOf($pids) -ne [IntPtr]::Zero) {
    $note = if ([KenshiPlace]::Demote([KenshiPlace]::ForegroundOf($pids))) { ' (foreground dropped)' } else { ' (STILL FOREGROUND)' }
  }
  $r = New-Object KenshiWin32+RECT; [KenshiWin32]::GetWindowRect($win.Handle, [ref]$r) | Out-Null
  "monitor=$([KenshiPlace]::MonitorOf($win.Handle)) rect=$($r.Left),$($r.Top) $($r.Right - $r.Left)x$($r.Bottom - $r.Top) foreground=$(Get-ForegroundDesc)$note"
}

function Get-Health {
  $procs = Get-KenshiProcs
  if ($procs.Count -eq 0) {
    $dump = Get-LatestCrashDump
    if ($dump -and $dump.LastWriteTime -gt (Get-Date).AddMinutes(-10)) { return "crashed (dump $($dump.Name) at $($dump.LastWriteTime))" }
    return 'not-running'
  }
  $win = Get-GameWindow
  if (-not $win) { if (Get-Launcher) { return 'launcher-open' } return 'no-window' }
  $p = Get-Process -Id $procs[0].ProcessId
  if (-not $p.Responding) { return 'hung (window not responding)' }
  return 'ok'
}

switch ($Command) {
  'status' {
    $procs = Get-KenshiProcs
    if ($procs.Count -eq 0) { 'not running'; break }
    foreach ($p in $procs) { "pid=$($p.ProcessId) started=$($p.CreationDate) cmd=$($p.CommandLine)" }
    "launcher open: $([bool](Get-Launcher))   game window: $([bool](Get-GameWindow))   health: $(Get-Health)"
  }
  'launch' { Start-Kenshi }
  'stop' {
    Save-Logs 'stop' | Out-Null; Stop-Kenshi
    # a later manual launch starts with normal input
    Remove-Item "$HarnessDir\input_isolation.flag", "$HarnessDir\input_isolation.on" -ErrorAction SilentlyContinue
  }
  'monitors' { [KenshiPlace]::Monitors() }
  'place' {
    $win = Get-GameWindow
    if (-not $win) { throw 'no game window' }
    $m = if ($Monitor) { $Monitor } else { throw 'place needs -Monitor <DISPLAYn>' }
    $where = ''; $err = [KenshiPlace]::Place($win.Handle, $m, [ref]$where)
    if ($err) { "not placed: $err"; exit 1 }
    "placed (not activated): $where; on monitor $([KenshiPlace]::MonitorOf($win.Handle)); foreground: $(Get-ForegroundDesc)"
  }
  'background' { Keep-BackgroundNow }
  'window' {
    $win = Get-GameWindow
    if (-not $win) { throw 'no game window' }
    $r = New-Object KenshiWin32+RECT; [KenshiWin32]::GetWindowRect($win.Handle, [ref]$r) | Out-Null
    "monitor=$([KenshiPlace]::MonitorOf($win.Handle)) rect=$($r.Left),$($r.Top) $($r.Right - $r.Left)x$($r.Bottom - $r.Top) (DPI-virtualized for this shell) foreground=$(Get-ForegroundDesc)"
  }
  'restart' { if ((Get-KenshiProcs).Count -gt 0) { Save-Logs 'restart' | Out-Null; Stop-Kenshi }; Start-Kenshi }
  'health' { $h = Get-Health; $h; if ($h -ne 'ok') { exit 1 } }
  'focus' {
    $win = Get-GameWindow
    if (-not $win) { throw 'no game window' }
    if ([KenshiWin32]::ForceForeground($win.Handle)) { 'focused'; break }
    $fg = [KenshiWin32]::GetForegroundWindow(); $fgPid = [uint32]0
    [KenshiWin32]::GetWindowThreadProcessId($fg, [ref]$fgPid) | Out-Null
    $fgName = if ($fgPid) { (Get-Process -Id $fgPid -ErrorAction SilentlyContinue).ProcessName } else { 'none' }
    $locked = [bool](Get-Process LogonUI -ErrorAction SilentlyContinue)
    "focus refused: foreground=$fg pid=$fgPid ($fgName) logonui=$locked"; exit 1
  }
  'screenshot' {
    Add-Type -Path (Join-Path $PSScriptRoot 'WindowCapture.cs') -ReferencedAssemblies System.Drawing
    $win = Get-GameWindow
    if (-not $win) { throw 'no game window' }
    $dir = Join-Path $ArchiveRoot 'shots'
    New-Item -ItemType Directory -Force $dir | Out-Null
    $path = if ($Save) { Join-Path $dir "$Save.png" } else { Join-Path $dir ("shot-" + (Get-Date -Format 'yyyyMMdd-HHmmss') + '.png') }
    $size = [KenshiCapture]::Save($win.Handle, $path, 1600)
    "$path ($size)"
  }
  default { throw "unknown command: $Command" }
}
