@echo off
REM =============================================================================
REM 测试 1: 单轮对话 — "推荐一款200元以下的防晒霜" + "推荐一款不含酒精的防晒霜"
REM
REM 用法:
REM   cd server && tests\test_agent_search\test_single_turn.bat
REM   set BASE_URL=http://localhost:8080 && tests\test_agent_search\test_single_turn.bat
REM =============================================================================

setlocal enabledelayedexpansion

REM ---- 配置 ----
if "%BASE_URL%"=="" set "BASE_URL=http://127.0.0.1:8000"
if "%TIMEOUT%"=="" set "TIMEOUT=300"

set "SCRIPT_DIR=%~dp0"

REM ---- 测试用例 ----

echo.
echo ================================================================================
echo   测试 1: 单轮对话 (2 个查询)
echo ================================================================================

set "overall_pass=1"

REM --- 查询 1a: 推荐一款200元以下的防晒霜 ---
echo.
echo   --- 查询 1a: "推荐一款200元以下的防晒霜" ---
call "%SCRIPT_DIR%_utils.bat" :new_conversation
echo [OK]    conversation_id: %cid%

set "TMPFILE=%TEMP%\test_search_1a_%RANDOM%.sse"
call "%SCRIPT_DIR%_utils.bat" :sse_search "推荐一款200元以下的防晒霜" "%cid%" "%TMPFILE%"
call "%SCRIPT_DIR%_utils.bat" :print_sse_summary "%TMPFILE%"

findstr /C:"event: welcome" "%TMPFILE%" >nul 2>&1
if errorlevel 1 (echo [FAIL]  查询 1a: 缺少 welcome 事件& set "overall_pass=0")
findstr /C:"event: products" "%TMPFILE%" >nul 2>&1
if errorlevel 1 (echo [FAIL]  查询 1a: 缺少 products 事件& set "overall_pass=0")
findstr /C:"event: done" "%TMPFILE%" >nul 2>&1
if errorlevel 1 (echo [FAIL]  查询 1a: 缺少 done 事件& set "overall_pass=0")
findstr /C:"event: next_options" "%TMPFILE%" >nul 2>&1
if errorlevel 1 (echo [FAIL]  查询 1a: 缺少 next_options 事件& set "overall_pass=0")
del /F /Q "%TMPFILE%" >nul 2>&1

REM --- 查询 1b: 推荐一款不含酒精的防晒霜 ---
echo.
echo   --- 查询 1b: "推荐一款不含酒精的防晒霜" ---
call "%SCRIPT_DIR%_utils.bat" :new_conversation
echo [OK]    conversation_id: %cid%

set "TMPFILE=%TEMP%\test_search_1b_%RANDOM%.sse"
call "%SCRIPT_DIR%_utils.bat" :sse_search "推荐一款不含酒精的防晒霜" "%cid%" "%TMPFILE%"
call "%SCRIPT_DIR%_utils.bat" :print_sse_summary "%TMPFILE%"

findstr /C:"event: welcome" "%TMPFILE%" >nul 2>&1
if errorlevel 1 (echo [FAIL]  查询 1b: 缺少 welcome 事件& set "overall_pass=0")
findstr /C:"event: products" "%TMPFILE%" >nul 2>&1
if errorlevel 1 (echo [FAIL]  查询 1b: 缺少 products 事件& set "overall_pass=0")
findstr /C:"event: done" "%TMPFILE%" >nul 2>&1
if errorlevel 1 (echo [FAIL]  查询 1b: 缺少 done 事件& set "overall_pass=0")
findstr /C:"event: next_options" "%TMPFILE%" >nul 2>&1
if errorlevel 1 (echo [FAIL]  查询 1b: 缺少 next_options 事件& set "overall_pass=0")
del /F /Q "%TMPFILE%" >nul 2>&1

if "%overall_pass%"=="1" (
    echo [OK]    测试 1 通过
) else (
    echo [FAIL]  测试 1 失败
)

echo.
echo ================================================================================
echo   测试完成
echo ================================================================================

endlocal
