@echo off
rem Harness board shortcut: double-click to launch the web editor.
rem Usage: board.cmd              (default port 8777, opens browser)
rem        board.cmd -Port 9000
rem (ASCII-only on purpose: cmd.exe misreads UTF-8 comment bytes.)
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0.harness\dashboard\serve.ps1" %*
