@echo off
REM =============================================================================
REM 测试 3: 场景化推荐 — "下周去三亚度假，帮我搭配一套从防晒到穿搭的方案"
REM
REM 用法:
REM   cd server && tests\test_agent_search\test_scenario.bat
REM   set BASE_URL=http://localhost:8080 && tests\test_agent_search\test_scenario.bat
REM =============================================================================

setlocal enabledelayedexpansion

REM ---- 配置 ----
if "%BASE_URL%"=="" set "BASE_URL=http://127.0.0.1:8000"
if "%TIMEOUT%"=="" set "TIMEOUT=300"

set "SCRIPT_DIR=%~dp0"

REM ---- 测试用例 ----

echo.
echo ================================================================================
echo   测试 3: 场景化推荐 - "下周去三亚度假，帮我搭配一套从防晒到穿搭的方案"
echo ================================================================================

call "%SCRIPT_DIR%_utils.bat" :new_conversation
echo [OK]    conversation_id: %cid%

set "TMPFILE=%TEMP%\test_search_3_%RANDOM%.sse"
call "%SCRIPT_DIR%_utils.bat" :sse_search "下周去三亚度假，帮我搭配一套从防晒到穿搭的方案" "%cid%" "%TMPFILE%"
call "%SCRIPT_DIR%_utils.bat" :print_sse_summary "%TMPFILE%"

for /f %%a in ('findstr /C:"event: products" "%TMPFILE%" 2^>nul ^| find /C "event: products"') do set "pc=%%a"
set "pass=1"
findstr /C:"event: welcome" "%TMPFILE%" >nul 2>&1
if errorlevel 1 (
    echo [FAIL]  测试 3: 缺少 welcome 事件
    set "pass=0"
)
findstr /C:"event: next_options" "%TMPFILE%" >nul 2>&1
if errorlevel 1 (
    echo [FAIL]  测试 3: 缺少 next_options 事件
    set "pass=0"
)
if %pc% GEQ 1 (
    if "%pass%"=="1" (
        echo [OK]    测试 3 通过: %pc% 个 products 事件
    ) else (
        echo [FAIL]  测试 3 失败: 缺少部分 SSE 事件
    )
) else (
    echo [FAIL]  测试 3 失败: 缺少 products 事件
)

del /F /Q "%TMPFILE%" >nul 2>&1

echo.
echo ================================================================================
echo   测试完成
echo ================================================================================

endlocal
