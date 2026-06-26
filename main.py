import os
import json
import time
import threading
import subprocess
from flask import Flask
import telebot

BOT_TOKEN = os.environ.get("BOT_TOKEN")
KAGGLE_USERNAME = os.environ.get("KAGGLE_USERNAME")
KAGGLE_KEY = os.environ.get("KAGGLE_KEY")

if not BOT_TOKEN:
    raise ValueError("❌ BOT_TOKEN is missing!")

bot = telebot.TeleBot(BOT_TOKEN)
app = Flask(__name__)
NOTEBOOK_DIR = "notebook_folder"

def setup_kaggle_credentials():
    if not KAGGLE_USERNAME or not KAGGLE_KEY:
        print("❌ Kaggle credentials missing!")
        return False
    
    clean_user = KAGGLE_USERNAME.strip().strip("'\"")
    clean_key = KAGGLE_KEY.strip().strip("'\"")
    
    os.environ["KAGGLE_USERNAME"] = clean_user
    os.environ["KAGGLE_KEY"] = clean_key
    
    kaggle_dir = os.path.expanduser("~/.kaggle")
    os.makedirs(kaggle_dir, exist_ok=True)
    with open(os.path.join(kaggle_dir, "kaggle.json"), "w") as f:
        json.dump({"username": clean_user, "key": clean_key}, f)
    os.chmod(os.path.join(kaggle_dir, "kaggle.json"), 0o600)
    
    print(f"✅ Kaggle ready for: {clean_user}")
    return True

def push_to_kaggle(chat_id):
    try:
        status = bot.send_message(chat_id, "📤 Pushing to Kaggle...")
        result = subprocess.run(["kaggle", "kernels", "push", "-p", NOTEBOOK_DIR], 
                              capture_output=True, text=True, timeout=180)
        
        if result.returncode == 0:
            bot.edit_message_text("✅ **Pushed Successfully!**\nWaiting for Kaggle confirmation...", chat_id, status.message_id)
        else:
            bot.edit_message_text(f"❌ Push failed:\n{result.stderr[:400]}", chat_id, status.message_id)
    except Exception as e:
        bot.send_message(chat_id, f"❌ Error: {e}")

@bot.message_handler(commands=['ready'])
def handle_ready(message):
    bot.reply_to(message, "🚀 Waking Kaggle...")
    if setup_kaggle_credentials():
        threading.Thread(target=push_to_kaggle, args=(message.chat.id,), daemon=True).start()

@bot.message_handler(commands=['start'])
def start(message):
    bot.reply_to(message, "Send /ready to wake Kaggle bot.")

@app.route('/')
def home():
    return "Bot A is Running"

if __name__ == "__main__":
    setup_kaggle_credentials()
    print("🤖 Starting Bot A...")
    bot.remove_webhook()
    time.sleep(2)
    bot.infinity_polling(none_stop=True, timeout=20)