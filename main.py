import pandas as pd
import requests
import time
from datetime import datetime
import threading
from flask import Flask
import os

# ==========================================
# CONFIGURATION SETTINGS
# ==========================================
TELEGRAM_BOT_TOKEN = "8992095386:AAFexnI8IRh990PlwZtkn6WkjeOV0yHjkCE"
TELEGRAM_CHAT_ID = "1136613703"

app = Flask(__name__)

def send_telegram_alert(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message}
    try:
        requests.post(url, json=payload, timeout=10)
    except Exception:
        pass

# ==========================================
# EVERY PING RUNS THE DUMMY TEST CODE
# ==========================================
@app.route('/')
def home():
    print("Incoming Ping! Running dummy test...")
    
    # Send the 3 exact test alerts like the old script did
    send_telegram_alert("👋 Hello from your Cloud Render Server! The connection works.")
    time.sleep(1)
    send_telegram_alert("🔄 Loop test message #1 from the server.")
    time.sleep(1)
    send_telegram_alert("✅ Test complete! If you see this, the tool is up and continuous.")
    
    return "Dummy test executed! Check your Telegram."

if __name__ == "__main__":
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port)
