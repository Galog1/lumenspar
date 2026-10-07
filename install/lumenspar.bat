@echo off
rem Lumenspar launcher for Windows (AI reader only).
rem Genshin runs elevated, so Windows only lets an elevated program send it
rem input: right-click this file and choose "Run as administrator".
cd /d "%~dp0.."
if exist ".venv\Scripts\python.exe" (".venv\Scripts\python.exe" -m lumenspar %* & goto :eof)
where py >nul 2>nul && (py -3 -m lumenspar %* & goto :eof)
python -m lumenspar %*
