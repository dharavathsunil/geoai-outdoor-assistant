Set-Location D:\GeoAI
Start-Process powershell -ArgumentList '-NoExit','-Command','cd D:\GeoAI; .venv\Scripts\Activate.ps1; uvicorn app:app --host 127.0.0.1 --port 8000'
Start-Sleep -Seconds 25
Start-Process powershell -ArgumentList '-NoExit','-Command','ngrok http 8000'