$ErrorActionPreference = 'Stop'
$uiPath = Join-Path $PSScriptRoot 'Win32Ui.cs'
$ctlPath = Join-Path $PSScriptRoot 'kenshi-ctl.ps1'
$ui = Get-Content -LiteralPath $uiPath -Raw
$ctl = Get-Content -LiteralPath $ctlPath -Raw

Add-Type -Path $uiPath
$cases = @(
  @{ Name='same captured app and game still foreground'; Identity=$true; Game=$true; DestinationGame=$false; Expected=$true },
  @{ Name='captured window went stale or was reused'; Identity=$false; Game=$true; DestinationGame=$false; Expected=$false },
  @{ Name='user switched to another app before keeper poll'; Identity=$true; Game=$false; DestinationGame=$false; Expected=$false },
  @{ Name='captured destination is now a game window'; Identity=$true; Game=$true; DestinationGame=$true; Expected=$false }
)
foreach ($case in $cases) {
  $actual = [KenshiPlace]::CanGiveBack($case.Identity, $case.Game, $case.DestinationGame)
  if ($actual -ne $case.Expected) { throw "focus predicate failed: $($case.Name) expected=$($case.Expected) actual=$actual" }
}

$keeperStart = $ctl.IndexOf('function Keep-Background {', [StringComparison]::Ordinal)
$keeperEnd = $ctl.IndexOf('function Keep-BackgroundNow {', [StringComparison]::Ordinal)
if ($keeperStart -lt 0 -or $keeperEnd -le $keeperStart) { throw 'Keep-Background function was not found' }
$keeperText = $ctl.Substring($keeperStart, $keeperEnd - $keeperStart)
if ($keeperText -notmatch '\$gameForeground\s*=\s*\[KenshiPlace\]::ForegroundOf\(\$pids\)' -or
    $keeperText -notmatch 'if \(\$Background -and \$gameForeground -eq \[IntPtr\]::Zero\)[\s\S]*?CaptureForeground\(\)' -or
    $keeperText -notmatch 'GiveBack\(\$script:PrevForeground,\s*\$gameForeground,\s*\$pids\)') {
  throw 'background keeper must refresh the current user foreground and pass the observed game HWND to GiveBack'
}
if ($keeperText -match 'ForceForeground|BringWindowToTop|keybd_event|SetCursorPos|ClipCursor|mouse_event|SendInput') {
  throw 'background keeper contains a focus-forcing or cursor/input API'
}

$giveBackStart = $ui.IndexOf('public static bool GiveBack(WindowToken prev, IntPtr observedGame, uint[] gamePids) {', [StringComparison]::Ordinal)
$giveBackEnd = $ui.IndexOf('public static IntPtr Foreground()', [StringComparison]::Ordinal)
if ($giveBackStart -lt 0 -or $giveBackEnd -le $giveBackStart) { throw 'GiveBack function was not found' }
$giveBackText = $ui.Substring($giveBackStart, $giveBackEnd - $giveBackStart)
if ($giveBackText -notmatch 'CanGiveBack\(previousIdentityMatches, foregroundStillGame, destinationIsGame\)' -or
    $giveBackText -notmatch 'CanGiveBack\(SameWindow\(prev\), GetForegroundWindow\(\) == observedGame, destinationIsGame\)[\s\S]*?SetForegroundWindow\(prev\.Handle\)') {
  throw 'GiveBack must verify window identity and recheck current game foreground immediately before activation'
}
if ($giveBackText -match 'SetCursorPos|ClipCursor|mouse_event|SendInput|keybd_event|BringWindowToTop') {
  throw 'GiveBack contains a cursor, input, or z-order API'
}

if ($ctl -notmatch '\[switch\]\$AutoAcceptModOrderWarning' -or $ctl -notmatch 'if \(\$AutoAcceptModOrderWarning\)') {
  throw 'existing mod-order warning opt-in was lost'
}

'RESULT background-focus-selftest PASS cases=4 desktop=untouched cursor=untouched'
