@echo off
chcp 65001 > nul
echo ======================================================================
echo    MSB ENTERPRISE BANKING AI CREDIT PROPOSAL COPILOT
echo ======================================================================
echo Dang khoi dong may chu Copilot tai cong 8550...
start http://localhost:8550
python web_copilot_app.py
pause
