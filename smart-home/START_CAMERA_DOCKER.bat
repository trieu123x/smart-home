@echo off
setlocal
cd /d "%~dp0" || exit /b 1
if not exist "backend\tools\adb\adb.exe" (
  echo Missing backend\tools\adb\adb.exe. Copy the bundled ADB tools first.
  exit /b 1
)
echo Connect the Android phone by USB and allow USB debugging on the phone.
echo This bridge lets Docker use the Windows USB camera through ADB port 5038.
echo Keep this terminal open. Ctrl+C stops the bridge.
echo Do not expose ports 5038 or 27183 to the Internet.
echo Stopping the default ADB server so this bridge can own the USB phone.
"backend\tools\adb\adb.exe" -P 5037 kill-server
"backend\tools\adb\adb.exe" -a -P 5038 nodaemon server
exit /b %errorlevel%
