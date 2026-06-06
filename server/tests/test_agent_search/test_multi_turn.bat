@echo off
REM =============================================================================
REM 测试 2: 多轮对话 — "帮我推荐跑鞋" → "要轻量的" → "预算 500 以内"
REM
REM 用法:
REM   cd server && tests\test_agent_search\test_multi_turn.bat
REM   set BASE_URL=http://localhost:8080 && tests\test_agent_search\test_multi_turn.bat
REM =============================================================================

setlocal enabledelayedexpansion

REM ---- 配置 ----
if "%BASE_URL%"=="" set "BASE_URL=http://127.0.0.1:8000"
if "%TIMEOUT%"=="" set "TIMEOUT=300"

set "SCRIPT_DIR=%~dp0"

REM ---- 测试用例 ----

echo.
echo ================================================================================
echo   测试 2: 多轮对话 - "帮我推荐跑鞋" -^> "要轻量的" -^> "预算 500 以内"
echo ================================================================================

call "%SCRIPT_DIR%_utils.bat" :new_conversation
echo [OK]    conversation_id: %cid%

set "pass=1"

REM Turn 1
echo [INFO]  --- Turn 1 ---
set "TMP1=%TEMP%\test_search_mt1_%RANDOM%.sse"
call "%SCRIPT_DIR%_utils.bat" :sse_search "帮我推荐跑鞋" "%cid%" "%TMP1%"
call "%SCRIPT_DIR%_utils.bat" :print_sse_summary "%TMP1%"
findstr /C:"event: products" "%TMP1%" >nul 2>&1
if errorlevel 1 (
    echo [FAIL]  Turn 1 失败: 缺少 products 事件
    set "pass=0"
)
del /F /Q "%TMP1%" >nul 2>&1

timeout /T 2 /NOBREAK >nul

REM Turn 2
echo [INFO]  --- Turn 2 ---
set "TMP2=%TEMP%\test_search_mt2_%RANDOM%.sse"
call "%SCRIPT_DIR%_utils.bat" :sse_search "要轻量的" "%cid%" "%TMP2%"
call "%SCRIPT_DIR%_utils.bat" :print_sse_summary "%TMP2%"
findstr /C:"event: products" "%TMP2%" >nul 2>&1
if errorlevel 1 (
    echo [FAIL]  Turn 2 失败: 缺少 products 事件
    set "pass=0"
)
del /F /Q "%TMP2%" >nul 2>&1

timeout /T 2 /NOBREAK >nul

REM Turn 3
echo [INFO]  --- Turn 3 ---
set "TMP3=%TEMP%\test_search_mt3_%RANDOM%.sse"
call "%SCRIPT_DIR%_utils.bat" :sse_search "预算 500 以内" "%cid%" "%TMP3%"
call "%SCRIPT_DIR%_utils.bat" :print_sse_summary "%TMP3%"
findstr /C:"event: products" "%TMP3%" >nul 2>&1
if errorlevel 1 (
    echo [FAIL]  Turn 3 失败: 缺少 products 事件
    set "pass=0"
)
del /F /Q "%TMP3%" >nul 2>&1

if "%pass%"=="1" (
    echo [OK]    测试 2 通过: 三轮对话全部有 products 事件
) else (
    echo [FAIL]  测试 2 失败
)

echo.
echo ================================================================================
echo   测试完成
echo ================================================================================

endlocal
