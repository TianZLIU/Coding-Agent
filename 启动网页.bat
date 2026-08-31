@echo off
rem 双击本文件即可启动网页版编程智能体（自动打开浏览器）
cd /d "%~dp0"
D:\venvs\coding-agent\Scripts\python.exe -m streamlit run web_app.py
