@echo off
rem =====================================================================
rem  etax-auto 初回セットアップ（この1回だけ）
rem  このファイルをダブルクリックしてください。
rem =====================================================================
setlocal
cd /d "%~dp0"
set PYTHONIOENCODING=cp932:replace

echo ============================================================
echo   etax-auto 初回セットアップ
echo ============================================================
echo.

rem --- Python を探す -------------------------------------------------
set PYEXE=
where py >nul 2>&1
if not errorlevel 1 set PYEXE=py -3
if not defined PYEXE (
    where python >nul 2>&1
    if not errorlevel 1 set PYEXE=python
)
if not defined PYEXE goto NOPYTHON

echo [1/3] Python を確認しました。
%PYEXE% --version
echo.

rem --- 必要な部品を入れる --------------------------------------------
echo [2/3] 必要な部品を入れます。数分かかります...
echo.
%PYEXE% -m pip install --upgrade pip
%PYEXE% -m pip install -r requirements-minimal.txt
if errorlevel 1 goto PIPERROR
echo.

set ANSWER=n
set /p ANSWER="  e-Taxへ自動ログインする方式（方式B）も使いますか？ (y/n) [n]: "
if /i not "%ANSWER%"=="y" goto SKIPB
echo.
echo   ブラウザ部品を入れます。さらに数分かかります...
%PYEXE% -m pip install playwright
%PYEXE% -m playwright install chromium
:SKIPB
echo.

rem --- 設定を確認する ------------------------------------------------
echo [3/3] 設定を確認します。
echo.
set PYTHONPATH=%~dp0src
%PYEXE% -m etax_auto check
echo.
echo ============================================================
echo   セットアップはここまでです。
echo.
echo   次にすること:
echo     1. 達人から顧問先マスタを CSV で書き出す
echo     2. その CSV をこのフォルダに置き、コマンドで取り込む
echo        （手順は docs\07_残りの作業.md）
echo     3. チェックリストの原本 3 枚をスキャンして templates\ に置く
echo ============================================================
pause
exit /b 0

:NOPYTHON
echo.
echo   Python が見つかりませんでした。
echo.
echo   https://www.python.org/downloads/windows/ から
echo   Python 3.11 以降をダウンロードし、
echo   インストーラ最初の画面で
echo       「Add python.exe to PATH」
echo   に必ずチェックを入れてインストールしてください。
echo.
echo   インストール後、このファイルをもう一度実行してください。
echo.
pause
exit /b 1

:PIPERROR
echo.
echo   部品の取得に失敗しました。
echo   社内ネットワークの制限が原因のことがあります。
echo   この画面を写真に撮って、池田までお知らせください。
echo.
pause
exit /b 1
