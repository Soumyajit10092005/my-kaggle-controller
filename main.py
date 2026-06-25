import os
import json
import threading
import subprocess
from flask import Flask
import telebot

# ==========================================
# 1. CONFIGURATION & CORE INITIALIZATION
# ==========================================
BOT_TOKEN = os.environ.get("BOT_TOKEN")
KAGGLE_USERNAME = os.environ.get("KAGGLE_USERNAME")
KAGGLE_KEY = os.environ.get("KAGGLE_KEY")

if not BOT_TOKEN:
    raise ValueError("❌ Critical Error: 'BOT_TOKEN' environment variable is missing!")

bot = telebot.TeleBot(BOT_TOKEN)
app = Flask(__name__)


# ==========================================
# 2. HELPER FUNCTIONS & AUTH SETUP
# ==========================================
def setup_kaggle_credentials():
    """Configures system variables and writes Kaggle tokens to disk based on modern vs legacy CLI specs."""
    if not KAGGLE_KEY:
        print("⚠️ Kaggle API Key/Token environment variable is missing. Skipping setup.")
        return

    clean_key = KAGGLE_KEY.strip("'\" ")
    clean_username = KAGGLE_USERNAME.strip("'\" ") if KAGGLE_USERNAME else ""

    try:
        # Establish a rock-solid configuration directory
        kaggle_dir = os.path.expanduser("~/.kaggle")
        os.makedirs(kaggle_dir, exist_ok=True)
        
        # 💡 FIX 1: Force the Kaggle CLI to look directly at this folder on Render
        os.environ['KAGGLE_CONFIG_DIR'] = kaggle_dir

        # 💡 FIX 2: Isolate legacy vs modern token sequencing to prevent conflicts
        if clean_username:
            # 🏢 LEGACY AUTH TYPE (username + key from old kaggle.json)
            print("🔑 Configuring Legacy Kaggle credentials format...")
            os.environ['KAGGLE_USERNAME'] = clean_username
            os.environ['KAGGLE_KEY'] = clean_key
            os.environ.pop('KAGGLEAPITOKEN', None)  # Wipe new token variable to prevent collision
            
            credentials = {"username": clean_username, "key": clean_key}
            config_path = os.path.join(kaggle_dir, "kaggle.json")
            with open(config_path, "w") as f:
                json.dump(credentials, f)
            os.chmod(config_path, 0o600)
            
            # Clear old modern files if they exist
            token_path = os.path.join(kaggle_dir, "accesstoken")
            if os.path.exists(token_path):
                os.remove(token_path)
        else:
            # 🚀 MODERN AUTH TYPE (Standalone token from the new Kaggle UI)
            print("⚡ Configuring Modern Standalone Kaggle API Token format...")
            os.environ['KAGGLEAPITOKEN'] = clean_key
            os.environ.pop('KAGGLE_USERNAME', None)
            os.environ.pop('KAGGLE_KEY', None)

            token_path = os.path.join(kaggle_dir, "accesstoken")
            with open(token_path, "w") as f:
                f.write(clean_key)
            os.chmod(token_path, 0o600)
            
            # Clear old legacy files if they exist
            config_path = os.path.join(kaggle_dir, "kaggle.json")
            if os.path.exists(config_path):
                os.remove(config_path)

        print("✅ Kaggle credentials isolated and synchronized to environment successfully.")
    except Exception as e:
        print(f"❌ Failed to build credentials file: {e}")


# ==========================================
# 3. FLASK WEB ROUTING
# ==========================================
@app.route('/')
def home():
    return "⚡ Kaggle Controller Node is Online"


# ==========================================
# 4. TELEGRAM BOT EVENT HANDLERS
# ==========================================
@bot.message_handler(commands=['ready'])
def trigger_kaggle_instance(message):
    chat_id = message.chat.id
    bot.send_message(chat_id, "🚀 Sending payload authentication keys to Kaggle API... Waking up GPU server nodes.")
    
    try:
        # 💡 FIX 3: Explicitly feed 'env=os.environ' to ensure the execution binary sees the keys
        result = subprocess.run(
            ["kaggle", "kernels", "push", "-p", "./notebook_folder"], 
            capture_output=True, 
            text=True,
            env=os.environ  
        )
        
        if result.returncode == 0:
            success_msg = (
                "⚙️ *Kaggle Cloud Virtual Machine is Booting!*\n"
                "Allocating VRAM, mounting checkpoint weights, and initializing handlers.\n\n"
                "⏳ Please wait 2-3 minutes; the Video Generation Engine will text you directly when online..."
            )
            bot.send_message(chat_id, success_msg, parse_mode="Markdown")
        else:
            raw_error = result.stderr.strip() or result.stdout.strip() or f"Unknown error (Code: {result.returncode})"
            clean_error = raw_error.replace("`", "").replace("*", "").replace("_", "")
            bot.send_message(chat_id, f"❌ *Kaggle API Handshake Refused*:\n\n```\n{clean_error}\n```", parse_mode="Markdown")
            
    except Exception as e:
        bot.send_message(chat_id, f"❌ Controller Exception:\n`{str(e)}`", parse_mode="Markdown")


# ==========================================
# 5. EXECUTION ROUTERS
# ==========================================
def run_tg_bot():
    try:
        print("🧹 Clearing old Telegram webhooks and dropping pending updates...")
        bot.delete_webhook(drop_pending_updates=True)
    except Exception as e:
        print(f"⚠️ Non-critical webhook cleanup warning: {e}")

    print("📡 Starting Telegram listener loop...")
    bot.infinity_polling()


if __name__ == "__main__":
    setup_kaggle_credentials()
    threading.Thread(target=run_tg_bot, daemon=True).start()
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)