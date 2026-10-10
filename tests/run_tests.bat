@echo off
rem Offline tests (no game needed). Same compiler setup as build.bat.
setlocal
set ROOT=%~dp0..\
if "%KAH_TOOLS%"=="" set KAH_TOOLS=C:\StobeBuildTools
where cl >nul 2>nul
if not errorlevel 1 goto have_cl
set VC64=%KAH_TOOLS%\v100\Program Files(64)\Microsoft Visual Studio 10.0\VC
set VCINC=%KAH_TOOLS%\v100x86\Program Files\Microsoft Visual Studio 10.0\VC\include
set VCLIB=%KAH_TOOLS%\v100x86\Program Files\Microsoft Visual Studio 10.0\VC\lib\amd64
set SDK71=%KAH_TOOLS%\sdk71\Program Files\Microsoft SDKs\Windows\v7.1
set PATH=%VC64%\bin\amd64;%SDK71%\Bin\x64;%SDK71%\Bin;%PATH%
set INCLUDE=%VCINC%;%SDK71%\Include
set LIB=%VCLIB%;%SDK71%\Lib\x64
:have_cl
if not exist "%ROOT%obj\tests" mkdir "%ROOT%obj\tests"
cl /nologo /EHa /MD /W3 /I"%ROOT%src" /Fo"%ROOT%obj\tests\\" /Fe"%ROOT%obj\tests\extensions_test.exe" ^
  "%ROOT%tests\extensions_test.cpp" "%ROOT%src\Extensions.cpp" > "%ROOT%obj\tests\build.log" 2>&1
if errorlevel 1 (type "%ROOT%obj\tests\build.log" & echo TEST BUILD FAILED & exit /b 1)
"%ROOT%obj\tests\extensions_test.exe"
if errorlevel 1 exit /b 1
cl /nologo /EHa /MD /W3 /I"%ROOT%src" /Fo"%ROOT%obj\tests\\" /Fe"%ROOT%obj\tests\search_radius_test.exe" ^
  "%ROOT%tests\search_radius_test.cpp" > "%ROOT%obj\tests\build_radius.log" 2>&1
if errorlevel 1 (type "%ROOT%obj\tests\build_radius.log" & echo TEST BUILD FAILED & exit /b 1)
"%ROOT%obj\tests\search_radius_test.exe"
if errorlevel 1 exit /b 1
cl /nologo /EHa /MD /W3 /I"%ROOT%src" /Fo"%ROOT%obj\tests\\" /Fe"%ROOT%obj\tests\build_args_test.exe" ^
  "%ROOT%tests\build_args_test.cpp" > "%ROOT%obj\tests\build_build_args.log" 2>&1
if errorlevel 1 (type "%ROOT%obj\tests\build_build_args.log" & echo TEST BUILD FAILED & exit /b 1)
"%ROOT%obj\tests\build_args_test.exe"
if errorlevel 1 exit /b 1
cl /nologo /EHa /MD /W3 /I"%ROOT%src" /Fo"%ROOT%obj\tests\\" /Fe"%ROOT%obj\tests\frame_stats_test.exe" ^
  "%ROOT%tests\frame_stats_test.cpp" > "%ROOT%obj\tests\build_frame_stats.log" 2>&1
if errorlevel 1 (type "%ROOT%obj\tests\build_frame_stats.log" & echo TEST BUILD FAILED & exit /b 1)
"%ROOT%obj\tests\frame_stats_test.exe"
if errorlevel 1 exit /b 1
cl /nologo /EHa /MD /W3 /I"%ROOT%src" /Fo"%ROOT%obj\tests\\" /Fe"%ROOT%obj\tests\production_counter_test.exe" ^
  "%ROOT%tests\production_counter_test.cpp" > "%ROOT%obj\tests\build_production.log" 2>&1
if errorlevel 1 (type "%ROOT%obj\tests\build_production.log" & echo TEST BUILD FAILED & exit /b 1)
"%ROOT%obj\tests\production_counter_test.exe"
if errorlevel 1 exit /b 1
cl /nologo /EHa /MD /W3 /I"%ROOT%src" /Fo"%ROOT%obj\tests\\" /Fe"%ROOT%obj\tests\character_ref_test.exe" ^
  "%ROOT%tests\character_ref_test.cpp" > "%ROOT%obj\tests\build_character_ref.log" 2>&1
if errorlevel 1 (type "%ROOT%obj\tests\build_character_ref.log" & echo TEST BUILD FAILED & exit /b 1)
"%ROOT%obj\tests\character_ref_test.exe"
if errorlevel 1 exit /b 1
cl /nologo /EHa /MD /W3 /I"%ROOT%src" /Fo"%ROOT%obj\tests\\" /Fe"%ROOT%obj\tests\import_flags_test.exe" ^
  "%ROOT%tests\import_flags_test.cpp" > "%ROOT%obj\tests\build_import_flags.log" 2>&1
if errorlevel 1 (type "%ROOT%obj\tests\build_import_flags.log" & echo TEST BUILD FAILED & exit /b 1)
"%ROOT%obj\tests\import_flags_test.exe"
if errorlevel 1 exit /b 1
cl /nologo /EHa /MD /W3 /I"%ROOT%src" /Fo"%ROOT%obj\tests\\" /Fe"%ROOT%obj\tests\hit_credit_test.exe" ^
  "%ROOT%tests\hit_credit_test.cpp" > "%ROOT%obj\tests\build_hit_credit.log" 2>&1
if errorlevel 1 (type "%ROOT%obj\tests\build_hit_credit.log" & echo TEST BUILD FAILED & exit /b 1)
"%ROOT%obj\tests\hit_credit_test.exe"
if errorlevel 1 exit /b 1
cl /nologo /EHa /MD /W3 /I"%ROOT%src" /Fo"%ROOT%obj\tests\\" /Fe"%ROOT%obj\tests\ranged_shots_test.exe" ^
  "%ROOT%tests\ranged_shots_test.cpp" > "%ROOT%obj\tests\build_ranged_shots.log" 2>&1
if errorlevel 1 (type "%ROOT%obj\tests\build_ranged_shots.log" & echo TEST BUILD FAILED & exit /b 1)
"%ROOT%obj\tests\ranged_shots_test.exe"
if errorlevel 1 exit /b 1
cl /nologo /EHa /MD /W3 /I"%ROOT%src" /Fo"%ROOT%obj\tests\\" /Fe"%ROOT%obj\tests\ground_owner_test.exe" ^
  "%ROOT%tests\ground_owner_test.cpp" > "%ROOT%obj\tests\build_ground_owner.log" 2>&1
if errorlevel 1 (type "%ROOT%obj\tests\build_ground_owner.log" & echo TEST BUILD FAILED & exit /b 1)
"%ROOT%obj\tests\ground_owner_test.exe"
if errorlevel 1 exit /b 1
cl /nologo /EHa /MD /W3 /I"%ROOT%src" /Fo"%ROOT%obj\tests\\" /Fe"%ROOT%obj\tests\walk_arrival_test.exe" ^
  "%ROOT%tests\walk_arrival_test.cpp" > "%ROOT%obj\tests\build_walk_arrival.log" 2>&1
if errorlevel 1 (type "%ROOT%obj\tests\build_walk_arrival.log" & echo TEST BUILD FAILED & exit /b 1)
"%ROOT%obj\tests\walk_arrival_test.exe"
if errorlevel 1 exit /b 1
cl /nologo /EHa /MD /W3 /I"%ROOT%src" /Fo"%ROOT%obj\tests\\" /Fe"%ROOT%obj\tests\hold_speed_test.exe" ^
  "%ROOT%tests\hold_speed_test.cpp" > "%ROOT%obj\tests\build_hold_speed.log" 2>&1
if errorlevel 1 (type "%ROOT%obj\tests\build_hold_speed.log" & echo TEST BUILD FAILED & exit /b 1)
"%ROOT%obj\tests\hold_speed_test.exe"
if errorlevel 1 exit /b 1
cl /nologo /EHa /MD /W3 /I"%ROOT%src" /Fo"%ROOT%obj\tests\\" /Fe"%ROOT%obj\tests\chatter_test.exe" ^
  "%ROOT%tests\chatter_test.cpp" > "%ROOT%obj\tests\build_chatter.log" 2>&1
if errorlevel 1 (type "%ROOT%obj\tests\build_chatter.log" & echo TEST BUILD FAILED & exit /b 1)
"%ROOT%obj\tests\chatter_test.exe"
if errorlevel 1 exit /b 1
cl /nologo /EHa /MD /W3 /I"%ROOT%src" /Fo"%ROOT%obj\tests\\" /Fe"%ROOT%obj\tests\accel_profile_test.exe" ^
  "%ROOT%tests\accel_profile_test.cpp" > "%ROOT%obj\tests\build_accel_profile.log" 2>&1
if errorlevel 1 (type "%ROOT%obj\tests\build_accel_profile.log" & echo TEST BUILD FAILED & exit /b 1)
"%ROOT%obj\tests\accel_profile_test.exe"
if errorlevel 1 exit /b 1
cl /nologo /EHa /MD /W3 /I"%ROOT%src" /Fo"%ROOT%obj\tests\\" /Fe"%ROOT%obj\tests\crime_args_test.exe" ^
  "%ROOT%tests\crime_args_test.cpp" > "%ROOT%obj\tests\build_crime_args.log" 2>&1
if errorlevel 1 (type "%ROOT%obj\tests\build_crime_args.log" & echo TEST BUILD FAILED & exit /b 1)
"%ROOT%obj\tests\crime_args_test.exe"
if errorlevel 1 exit /b 1
cl /nologo /EHa /MD /W3 /I"%ROOT%src" /Fo"%ROOT%obj\tests\\" /Fe"%ROOT%obj\tests\race_filter_test.exe" ^
  "%ROOT%tests\race_filter_test.cpp" > "%ROOT%obj\tests\build_race_filter.log" 2>&1
if errorlevel 1 (type "%ROOT%obj\tests\build_race_filter.log" & echo TEST BUILD FAILED & exit /b 1)
"%ROOT%obj\tests\race_filter_test.exe"
if errorlevel 1 exit /b 1
cl /nologo /EHa /MD /W3 /I"%ROOT%src" /Fo"%ROOT%obj\tests\\" /Fe"%ROOT%obj\tests\protect_rules_test.exe" ^
  "%ROOT%tests\protect_rules_test.cpp" > "%ROOT%obj\tests\build_protect_rules.log" 2>&1
if errorlevel 1 (type "%ROOT%obj\tests\build_protect_rules.log" & echo TEST BUILD FAILED & exit /b 1)
"%ROOT%obj\tests\protect_rules_test.exe"
if errorlevel 1 exit /b 1
cl /nologo /EHa /MD /W3 /I"%ROOT%src" /Fo"%ROOT%obj\tests\\" /Fe"%ROOT%obj\tests\input_inject_test.exe" ^
  "%ROOT%tests\input_inject_test.cpp" > "%ROOT%obj\tests\build_input_inject.log" 2>&1
if errorlevel 1 (type "%ROOT%obj\tests\build_input_inject.log" & echo TEST BUILD FAILED & exit /b 1)
"%ROOT%obj\tests\input_inject_test.exe"
if errorlevel 1 exit /b 1
rem Scenario runner stops when the game leaves the world (item 122); needs Python 3.
where py >nul 2>nul
if not errorlevel 1 (py -3 "%ROOT%tests\kah_world_lost_test.py") else (python "%ROOT%tests\kah_world_lost_test.py")
if errorlevel 1 exit /b 1
rem Scenario @log step (paths with spaces); needs Python 3.
where py >nul 2>nul
if not errorlevel 1 (py -3 "%ROOT%tests\kah_log_step_test.py") else (python "%ROOT%tests\kah_log_step_test.py")
if errorlevel 1 exit /b 1
rem Scenario @any step (alternatives until one passes); needs Python 3.
where py >nul 2>nul
if not errorlevel 1 (py -3 "%ROOT%tests\kah_any_step_test.py") else (python "%ROOT%tests\kah_any_step_test.py")
if errorlevel 1 exit /b 1
rem Inbox protocol (client/kah.py with concurrent clients); needs Python 3 (py or python).
where py >nul 2>nul
if not errorlevel 1 (py -3 "%ROOT%tests\kah_inbox_test.py") else (python "%ROOT%tests\kah_inbox_test.py")
