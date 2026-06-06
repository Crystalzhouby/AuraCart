@echo off
REM =============================================================================
REM Agent 搜索服务集成测试 — 运行全部三个场景 (Windows Batch)
REM =============================================================================
REM
REM 用法:
REM   cd server && tests\test_agent_search\test_agent_search.bat
REM   set BASE_URL=http://localhost:8080 && tests\test_agent_search\test_agent_search.bat
REM
REM 单独运行某个场景:
REM   tests\test_agent_search\test_single_turn.bat    # 测试 1: 单轮对话
REM   tests\test_agent_search\test_multi_turn.bat     # 测试 2: 多轮对话
REM   tests\test_agent_search\test_scenario.bat       # 测试 3: 场景化推荐
REM =============================================================================

setlocal enabledelayedexpansion

if "%BASE_URL%"=="" set "BASE_URL=http://127.0.0.1:8000"
if "%TIMEOUT%"=="" set "TIMEOUT=300"

set "SCRIPT_DIR=%~dp0"

echo.
echo ================================================================================
echo   AuraCart Agent 搜索服务集成测试 (Windows Batch)
echo   服务地址: %BASE_URL%
echo ================================================================================

REM 前置检查
call "%SCRIPT_DIR%_utils.bat" :precheck

REM 运行三个测试场景（委托给独立脚本）
call "%SCRIPT_DIR%test_single_turn.bat"
call "%SCRIPT_DIR%test_multi_turn.bat"
call "%SCRIPT_DIR%test_scenario.bat"

echo.
echo ================================================================================
echo   全部测试完成
echo ================================================================================

endlocal
