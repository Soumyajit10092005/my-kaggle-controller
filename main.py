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
    """Configures system variables and writes physical Kaggle tokens to disk."""
    if not KAGGLE_USERNAME or not KAGGLE_KEY:
        print("⚠️ Kaggle environment variables are incomplete. Skipping disk setup.")
        return

    clean_username = KAGGLE_USERNAME.strip("'\" ")
    clean_key = KAGGLE_KEY.strip("'\" ")

    # Map variables to system environment (Legacy + New CLI standard)
    os.environ['KAGGLE_USERNAME'] = clean_username
    os.environ['KAGGLE_KEY'] = clean_key
    os.environ['KAGGLEAPITOKEN'] = clean_key 

    try:
        kaggle_dir = os.path.expanduser("~/.kaggle")
        os.makedirs(kaggle_dir, exist_ok=True)
        
        # 1. Legacy JSON Authentication Style
        credentials = {"username": clean_username, "key": clean_key}
        config_path = os.path.join(kaggle_dir, "kaggle.json")
        with open(config_path, "w") as f:
            json.dump(credentials, f)
        os.chmod(config_path, 0o600)

        # 2. Modern Token Authentication Style
        token_path = os.path.join(kaggle_dir, "accesstoken")
        with open(token_path, "w") as f:
            f.write(clean_key)
        os.chmod(token_path, 0o600)

        print("✅ All physical Kaggle credentials files synchronized to disk successfully.")
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
        # Execute the kernel push command cleanly
        result = subprocess.run(
            ["kaggle", "kernels", "push", "-p", "./notebook_folder"], 
            capture_output=True, 
            text=True
        )
        
        if result.returncode == 0:
            success_msg = (
                "⚙️ **Kaggle Cloud Virtual Machine is Booting!**\n"
                "Allocating VRAM, mounting checkpoint weights, and initializing handlers.\n\n"
                "⏳ Please wait 2-3 minutes; the Video Generation Engine will text you directly when online..."
            )
            bot.send_message(chat_id, success_msg)
        else:
            # Fallback capture stream extraction 
            raw_error = result.stderr.strip() or result.stdout.strip() or f"Unknown error (Code: {result.returncode})"
            clean_error = raw_error.replace("`", "").replace("*", "").replace("_", "")
            bot.send_message(chat_id, f"❌ Kaggle API Handshake Refused:\n\n{clean_error}")
            
    except Exception as e:
        bot.send_message(chat_id, f"❌ Controller Exception: {str(e)}")


# ==========================================
# 5. EXECUTION ROUTERS
# ==========================================
def run_tg_bot():
    print("📡 Starting Telegram listener loop...")
    bot.infinity_polling()


if __name__ == "__main__":
    # 1. Initialize environment setup first
    setup_kaggle_credentials()
    
    # 2. Fire up the Telegram polling thread background service
    threading.Thread(target=run_tg_bot, daemon=True).start()
    
    # 3. Spin up the primary Flask web process (Blocks main thread to keep service alive)
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
