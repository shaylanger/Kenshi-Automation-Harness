@echo off
rem Builds out\AutomationHarness.dll with the VS2010 x64 compiler (KenshiLib
rem plugins need the VS2010 runtime ABI) and Windows SDK 7.1.
rem
rem Paths (set them before running to override):
rem   KAH_TOOLS  extracted VS2010 x64 compiler + SDK 7.1 (v100, v100x86, sdk71 folders)
rem   KAH_SDK    KenshiLib SDK: Include\ (core, kenshi, ogre, mygui), KenshiLib.lib,
rem              Libraries\OgreMain_x64.lib, Libraries\MyGUIEngine_x64.lib
rem   KAH_BOOST  Boost headers (the version KenshiLib uses)
rem If cl.exe from VS2010 is already on PATH (VS2010 x64 command prompt), KAH_TOOLS is not used.
setlocal EnableDelayedExpansion
set ROOT=%~dp0
if "%KAH_TOOLS%"=="" set KAH_TOOLS=C:\StobeBuildTools
if "%KAH_SDK%"=="" set KAH_SDK=C:\StobeBuild\sdk
if "%KAH_BOOST%"=="" set KAH_BOOST=C:\StobeBuild\boost

rem (no parenthesised block here: PATH contains "Program Files (x86)")
where cl >nul 2>nul
if errorlevel 1 goto use_tools
cl 2>&1 | findstr /C:"Version 16." >nul
if not errorlevel 1 goto have_cl
:use_tools
set VC64=%KAH_TOOLS%\v100\Program Files(64)\Microsoft Visual Studio 10.0\VC
set VCINC=%KAH_TOOLS%\v100x86\Program Files\Microsoft Visual Studio 10.0\VC\include
set VCLIB=%KAH_TOOLS%\v100x86\Program Files\Microsoft Visual Studio 10.0\VC\lib\amd64
set SDK71=%KAH_TOOLS%\sdk71\Program Files\Microsoft SDKs\Windows\v7.1
set PATH=%VC64%\bin\amd64;%SDK71%\Bin\x64;%SDK71%\Bin;%PATH%
set INCLUDE=%VCINC%;%SDK71%\Include
set LIB=%VCLIB%;%SDK71%\Lib\x64
:have_cl
where cl >nul 2>nul || (echo ERROR: cl.exe not found: set KAH_TOOLS or use a VS2010 x64 prompt & exit /b 2)
cl 2>&1 | findstr /C:"Version 16." >nul || (echo ERROR: cl.exe is not the VS2010 compiler: & cl 2>&1 | findstr /C:"Version" & exit /b 2)
if not exist "%KAH_SDK%\KenshiLib.lib" (echo ERROR: KenshiLib SDK not found in %KAH_SDK% & exit /b 2)
if not exist "%KAH_BOOST%\boost" (echo ERROR: Boost headers not found in %KAH_BOOST% & exit /b 2)

if exist "%ROOT%obj" rmdir /s /q "%ROOT%obj"
if not exist "%ROOT%out" mkdir "%ROOT%out"
mkdir "%ROOT%obj"

set SOURCES=Plugin Commands Extensions Inventory InputIsolation

set CFLAGS=/nologo /c /MD /O2 /Ob2 /GL /GR /EHa /W3 /Zi /DWIN32 /D_WINDOWS /DNDEBUG /DUNICODE /D_UNICODE /DBOOST_ALL_NO_LIB /DBOOST_ERROR_CODE_HEADER_ONLY /DBOOST_SYSTEM_NO_DEPRECATED
set INCS=/I"%ROOT%compat" /I"%ROOT%src" /I"%KAH_SDK%\Include" /I"%KAH_SDK%\Include\ogre" /I"%KAH_SDK%\Include\mygui" /I"%KAH_BOOST%"

set FAILED=0
for %%S in (%SOURCES%) do (
  echo [compile] %%S.cpp
  cl %CFLAGS% %INCS% /Fo"%ROOT%obj\%%S.obj" /Fd"%ROOT%obj\vc100.pdb" "%ROOT%src\%%S.cpp" > "%ROOT%obj\%%S.log" 2>&1
  if errorlevel 1 (
    set FAILED=1
    echo ERROR compiling %%S.cpp:
    findstr /R /C:"error" "%ROOT%obj\%%S.log"
  )
)
if "%FAILED%"=="1" (echo BUILD FAILED during compile & exit /b 1)

echo [link] AutomationHarness.dll
link /nologo /DLL /LTCG /DEBUG /OPT:REF /OPT:ICF /MACHINE:X64 /OUT:"%ROOT%out\AutomationHarness.dll" /PDB:"%ROOT%out\AutomationHarness.pdb" ^
  "%ROOT%obj\*.obj" "%KAH_SDK%\KenshiLib.lib" "%KAH_SDK%\Libraries\MyGUIEngine_x64.lib" "%KAH_SDK%\Libraries\OgreMain_x64.lib" ^
  kernel32.lib user32.lib > "%ROOT%obj\link.log" 2>&1
if errorlevel 1 (type "%ROOT%obj\link.log" & echo BUILD FAILED during link & exit /b 1)

dumpbin /nologo /exports "%ROOT%out\AutomationHarness.dll" > "%ROOT%out\exports.txt"
echo BUILD OK: %ROOT%out\AutomationHarness.dll
exit /b 0
