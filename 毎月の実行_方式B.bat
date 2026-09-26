@echo off
rem =====================================================================
rem  毎月の通知書取得（方式B：e-Tax へ自動ログイン）
rem  初回セットアップでブラウザ部品を入れた場合のみ使えます。
rem =====================================================================
setlocal
cd /d "%~dp0"
set PYTHONIOENCODING=cp932:replace
set PYTHONPATH=%~dp0src

set PYEXE=
where py >nul 2>&1
if not errorlevel 1 set PYEXE=py -3
if not defined PYEXE (
    where python >nul 2>&1
    if not errorlevel 1 set PYEXE=python
)
if not defined PYEXE goto NOPYTHON

echo.
echo ============================================================
echo   今月の対象関与先
echo ============================================================
%PYEXE% -m etax_auto plan
if errorlevel 1 goto PLANERROR

echo.
echo   これから e-Tax へ自動でログインします。
echo   実行中はこの PC を操作しないでください。
echo.
set ANSWER=n
set /p ANSWER="  実行しますか？ (y/n) [n]: "
if /i not "%ANSWER%"=="y" goto CANCELLED

echo.
%PYEXE% -m etax_auto run
echo.
echo   出力された _束ね.pdf を片面印刷してください。
echo.
start "" "%~dp0out"
pause
exit /b 0

:PLANERROR
echo.
echo   対象の確認でエラーになりました。data\clients.csv をご確認ください。
pause
exit /b 1

:CANCELLED
echo   中止しました。
pause
exit /b 0

:NOPYTHON
echo.
echo   Python が見つかりません。先に「初回セットアップ.bat」を実行してください。
pause
exit /b 1
