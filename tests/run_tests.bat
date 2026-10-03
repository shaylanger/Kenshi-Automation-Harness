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
