@echo off
rem =====================================================================
rem  毎月15日頃の決算通知書取得
rem  このファイルをダブルクリックするだけで実行できます。
rem =====================================================================
chcp 65001 > nul
cd /d "%~dp0"

if not exist ".venv\Scripts\activate.bat" (
    echo セットアップがまだです。docs\02_セットアップ手順.md をご覧ください。
    pause
    exit /b 1
)
call .venv\Scripts\activate.bat

echo.
echo ============================================
echo   今月の対象関与先
echo ============================================
etax-auto plan
if errorlevel 1 goto :error

echo.
set /p ANSWER="この内容で実行しますか？ (y/n): "
if /i not "%ANSWER%"=="y" (
    echo 中止しました。
    pause
    exit /b 0
)

echo.
etax-auto run
echo.
echo 出力された _束ね.pdf を片面印刷してください。
pause
exit /b 0

:error
echo.
echo 対象の確認でエラーになりました。data\clients.csv をご確認ください。
pause
exit /b 1
