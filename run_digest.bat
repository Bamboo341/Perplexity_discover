@echo off
cd /d %~dp0

rem Force UTF-8 for Python I/O (Windows defaults to cp932)
set PYTHONUTF8=1

rem Locale-independent date; %date% format depends on regional settings
for /f %%i in ('powershell -NoProfile -Command "Get-Date -Format yyyy-MM-dd"') do set TODAY=%%i
set LOG=logs\%TODAY%.log

if not exist logs mkdir logs

call venv\Scripts\activate

rem Delete previous transients so a silent failure of step 2 cannot
rem re-deliver yesterday's digest (defense in depth with sink date checks)
del /q data\items.json data\digest.json 2>nul

rem Steps 1-2: abort the whole pipeline on failure (no artifacts exist yet)
python collect.py >> %LOG% 2>&1 || goto :fail
call claude -p "/digest" --allowedTools "Read,Write,WebFetch" >> %LOG% 2>&1 || goto :fail

rem Steps 3-4: independent sinks; one failing must not stop the other
set ERR=0
python send_discord.py >> %LOG% 2>&1 || set ERR=1

python render_md.py >> %LOG% 2>&1
if %errorlevel%==0 (
  git add digest data\archive README.md >> %LOG% 2>&1
  git diff --cached --quiet || git commit -m "digest: %TODAY%" >> %LOG% 2>&1 || set ERR=1
  git push >> %LOG% 2>&1 || set ERR=1
) else (
  set ERR=1
)

exit /b %ERR%

:fail
echo [ERROR] pipeline aborted >> %LOG%
exit /b 1
