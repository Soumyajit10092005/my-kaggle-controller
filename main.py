import os
import json
import time
import threading
import subprocess
from flask import Flask
import telebot

# ====================== CONFIG ======================
BOT_TOKEN = os.environ.get("BOT_TOKEN")
KAGGLE_USERNAME = os.environ.get("KAGGLE_USERNAME")
KAGGLE_KEY = os.environ.get("KAGGLE_KEY")

if not BOT_TOKEN:
    raise ValueError("❌ BOT_TOKEN is missing!")

bot = telebot.TeleBot(BOT_TOKEN)
app = Flask(__name__)
NOTEBOOK_DIR = "notebook_folder"

print(f"🔑 Kaggle Username from env: {KAGGLE_USERNAME}")
print(f"🔑 Kaggle Key length: {len(KAGGLE_KEY) if KAGGLE_KEY else 0}")

# ====================== KAGGLE SETUP ======================
def setup_kaggle_credentials():
    global KAGGLE_USERNAME, KAGGLE_KEY
    
    if not KAGGLE_USERNAME or not KAGGLE_KEY:
        print("❌ Kaggle credentials not found in environment variables!")
        return False
    
    # Clean the values
    KAGGLE_USERNAME = KAGGLE_USERNAME.strip().strip("'\"")
    KAGGLE_KEY = KAGGLE_KEY.strip().strip("'\"")
    
    os.environ["KAGGLE_USERNAME"] = KAGGLE_USERNAME
    os.environ["KAGGLE_KEY"] = KAGGLE_KEY
    
    # Create kaggle.json (important for Render)
    kaggle_dir = os.path.expanduser("~/.kaggle")
    os.makedirs(kaggle_dir, exist_ok=True)
    
    config_path = os.path.join(kaggle_dir, "kaggle.json")
    with open(config_path, "w") as f:
        json.dump({"username": KAGGLE_USERNAME, "key": KAGGLE_KEY}, f)
    os.chmod(config_path, 0o600)
    
    print("✅ Kaggle credentials configured successfully!")
    return True

# ====================== PUSH TO KAGGLE ======================
def push_to_kaggle(chat_id):
    try:
        status_msg = bot.send_message(chat_id, "📤 Pushing notebook to Kaggle...")
        
        result = subprocess.run(
            ["kaggle", "kernels", "push", "-p", NOTEBOOK_DIR],
            capture_output=True,
            text=True,
            timeout=120
        )
        
        if result.returncode == 0:
            bot.edit_message_text(
                "✅ **Successfully pushed to Kaggle!**\n\nWaiting for Bot B confirmation message...", 
                chat_id, status_msg.message_id
            )
        else:
            bot.edit_message_text(
                f"❌ Push failed:\n{result.stderr[:600]}", 
                chat_id, status_msg.message_id
            )
    except Exception as e:
        bot.send_message(chat_id, f"❌ Error: {str(e)}")

# ====================== COMMANDS ======================
@bot.message_handler(commands=['ready'])
def handle_ready(message):
    bot.reply_to(message, "🚀 Waking up Kaggle Notebook...")
    
    if setup_kaggle_credentials():
        threading.Thread(target=push_to_kaggle, args=(message.chat.id,), daemon=True).start()
    else:
        bot.send_message(message.chat.id, "❌ Kaggle credentials missing!\nCheck Render Environment Variables.")

@bot.message_handler(commands=['start'])
def start(message):
    bot.reply_to(message, "Send /ready to wake up Kaggle Video Bot.")

# ====================== FLASK ======================
@app.route('/')
def home():
    return "✅ Telegram + Kaggle Bot is Running!"

if __name__ == "__main__":
    setup_kaggle_credentials()
    print("🤖 Render Bot Started Successfully!")
    bot.infinity_polling()