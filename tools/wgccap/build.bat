@echo off
rem Builds tools\wgccap\out\wgccap.exe (Windows Graphics Capture -> raw BGRA named pipe for ffmpeg; see wgccap.cpp header).
rem Needs VS2019/2022 C++ x64 + Windows SDK 10.0.19041+ (C++/WinRT headers). Static CRT: runs on any Windows 10 2004+ PC.
setlocal
set ROOT=%~dp0
for /f "usebackq tokens=*" %%i in (`"%ProgramFiles(x86)%\Microsoft Visual Studio\Installer\vswhere.exe" -latest -products * -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath`) do set VSDIR=%%i
if "%VSDIR%"=="" echo no VS C++ toolset & exit /b 1
call "%VSDIR%\VC\Auxiliary\Build\vcvars64.bat" >nul || exit /b 1
if not exist "%ROOT%out" mkdir "%ROOT%out"
cl /nologo /std:c++17 /EHsc /O2 /MT /W3 /DUNICODE /D_UNICODE /DWIN32_LEAN_AND_MEAN /DNOMINMAX "%ROOT%wgccap.cpp" /Fo"%ROOT%out\\" /Fe"%ROOT%out\wgccap.exe" /link /SUBSYSTEM:CONSOLE
exit /b %errorlevel%
