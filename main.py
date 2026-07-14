
import requests
import time
from datetime import datetime

# ==========================================
# PASTE YOUR DETAILS HERE
# ==========================================
TELEGRAM_BOT_TOKEN = "8992095386:AAfexnI8IRh990PlwZtkn6WkjeOV0yHjkCE"  # From your Notepad screenshot
TELEGRAM_CHAT_ID = "1136613703"                                      # From your Notepad screenshot

def send_telegram_alert(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message}
    try:
        response = requests.post(url, json=payload)
        if response.status_code == 200:
            print(f"[{datetime.now().strftime('%H:%M:%S')}] ✅ Success! Message delivered to Telegram.")
        else:
            print(f"❌ Failed! Telegram API responded with: {response.text}")
    except Exception as e:
        print(f"❌ Network Error: Could not reach Telegram server. Details: {e}")

# ==========================================
# RUN THE VM TEST
# ==========================================
print("🚀 Starting Dummy Server Test from VM...")

# Test 1: Immediate verification message
send_telegram_alert("👋 Hello from your Cloud VM! The basic connection works.")

# Test 2: Simulating a tiny 2-step loop to ensure stability
print("Running loop check...")
for i in range(1, 3):
    time.sleep(3)
    send_telegram_alert(f"🔄 Loop test message #{i} from the server.")

print("🏁 Test complete! If your phone received 3 alerts, your VM can talk to Telegram.")
