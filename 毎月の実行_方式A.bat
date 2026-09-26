@echo off
rem =====================================================================
rem  毎月の通知書取得（方式A：達人で落とした PDF を取り込む）
rem
rem  使い方は2通りです。
rem    1. 達人で落とした PDF の入ったフォルダを、
rem       このファイルの上にドラッグ＆ドロップする
rem    2. このファイルをダブルクリックし、あとでフォルダを指定する
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

rem --- 取り込み元フォルダ --------------------------------------------
set SRCDIR=%~1
if not defined SRCDIR (
    echo.
    echo   達人で落とした PDF の入ったフォルダを指定してください。
    echo   （フォルダをこの画面にドラッグ＆ドロップしても入ります）
    echo.
    set /p SRCDIR="  フォルダ: "
)
if not defined SRCDIR goto NODIR
rem 前後の引用符を外す
set SRCDIR=%SRCDIR:"=%
if not exist "%SRCDIR%" goto NODIR

rem --- 今月の対象を見せて、確認を取る --------------------------------
echo.
echo ============================================================
echo   今月の対象関与先
echo ============================================================
%PYEXE% -m etax_auto plan
if errorlevel 1 goto PLANERROR

echo.
set ANSWER=n
set /p ANSWER="  この内容で実行しますか？ (y/n) [n]: "
if /i not "%ANSWER%"=="y" goto CANCELLED

rem --- 実行 -----------------------------------------------------------
echo.
%PYEXE% -m etax_auto run --from-dir "%SRCDIR%"
echo.
echo ============================================================
echo   出力された _束ね.pdf を片面印刷してください。
echo   「要確認」と出た関与先は _結果一覧.csv をご覧ください。
echo ============================================================
echo.
start "" "%~dp0out"
pause
exit /b 0

:NODIR
echo.
echo   フォルダが指定されていない、または見つかりません。
echo.
pause
exit /b 1

:PLANERROR
echo.
echo   対象の確認でエラーになりました。
echo   data\clients.csv をご確認ください。
echo.
pause
exit /b 1

:CANCELLED
echo   中止しました。
pause
exit /b 0

:NOPYTHON
echo.
echo   Python が見つかりません。先に「初回セットアップ.bat」を実行してください。
echo.
pause
exit /b 1
