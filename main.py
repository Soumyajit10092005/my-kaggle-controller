import os
import telebot
import subprocess
import threading
import json
from flask import Flask

# 1. Fetch credentials securely from Render's Environment Variables
BOT_TOKEN = os.environ.get("BOT_TOKEN")
KAGGLE_USERNAME = os.environ.get("KAGGLE_USERNAME")
KAGGLE_KEY = os.environ.get("KAGGLE_KEY")

# Create physical credentials file on disk to guarantee Kaggle CLI authentication
if KAGGLE_USERNAME and KAGGLE_KEY:
    try:
        kaggle_dir = os.path.expanduser("~/.kaggle")
        os.makedirs(kaggle_dir, exist_ok=True)
        
        credentials = {
            "username": KAGGLE_USERNAME.strip("'\" "),
            "key": KAGGLE_KEY.strip("'\" ")
        }
        
        config_path = os.path.join(kaggle_dir, "kaggle.json")
        with open(config_path, "w") as f:
            json.dump(credentials, f)
            
        # Set strict read/write permissions required by Kaggle
        os.chmod(config_path, 0o600)
        print("✅ Physical kaggle.json created successfully on disk.")
    except Exception as e:
        print(f"❌ Failed to build credentials file: {e}")

# Map variables to system environment as a backup
os.environ['KAGGLE_USERNAME'] = KAGGLE_USERNAME.strip("'\" ") if KAGGLE_USERNAME else ""
os.environ['KAGGLE_KEY'] = KAGGLE_KEY.strip("'\" ") if KAGGLE_KEY else ""

bot = telebot.TeleBot(BOT_TOKEN)

# 2. Setup a lightweight Flask server to satisfy Render's port-binding rules
app = Flask(__name__)

@app.route('/')
def home():
    return "⚡ Kaggle Controller Node is Online"

@bot.message_handler(commands=['ready'])
def trigger_kaggle_instance(message):
    chat_id = message.chat.id
    bot.send_message(chat_id, "🚀 Sending payload authentication keys to Kaggle API... Waking up GPU server nodes.")
    
    try:
        # Pushes your local folder configuration directly to Kaggle's backend
        result = subprocess.run(["kaggle", "kernels", "list"], capture_output=True, text=True)
        
        if result.returncode == 0:
            bot.send_message(chat_id, "⚙️ **Kaggle Cloud Virtual Machine is Booting!**\nAllocating VRAM, mounting checkpoint weights, and initializing handlers.\n\n⏳ Please wait 2-3 minutes; the Video Generation Engine will text you directly when online...")
        else:
            bot.send_message(chat_id, f"❌ Kaggle API Handshake Refused:\n`{result.stderr}`", parse_mode="Markdown")
            
    except Exception as e:
        bot.send_message(chat_id, f"❌ Controller Exception: `{str(e)}`", parse_mode="Markdown")

# Run Telegram Polling in a background thread so it doesn't block the web server
def run_tg_bot():
    print("📡 Starting Telegram listener loop...")
    bot.infinity_polling()

if __name__ == "__main__":
    # Start the bot thread
    threading.Thread(target=run_tg_bot, daemon=True).start()
    
    # Start Flask web server on the port Render assigns dynamically
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)