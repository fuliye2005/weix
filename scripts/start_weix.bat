@echo off
title Weix - WeChat Bot
cd /d "%~dp0"

echo ==========================================
echo  Weix 微信自动回复机器人
echo ==========================================

REM 检查可执行文件是否存在
if not exist "Weix.exe" (
    echo 错误: 找不到 Weix.exe
    echo 请确保在正确的目录中运行此脚本
    pause
    exit /b 1
)

REM 配置和数据目录会在 Weix.exe 首次启动时自动创建。
if not exist "config" mkdir config
if not exist "data" mkdir data

echo 正在启动服务...
echo 管理界面: http://127.0.0.1:8000
echo.

REM 启动器自身包含 GUI、后端和打包后的前端静态资源。
start "Weix" /D "%~dp0" "Weix.exe"
