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
    """Configures and writes ALL legacy and modern Kaggle credentials simultaneously."""
    if not KAGGLE_KEY:
        print("⚠️ Kaggle API Key/Token environment variable is missing. Skipping setup.")
        return

    clean_key = KAGGLE_KEY.strip("'\" ")
    clean_username = KAGGLE_USERNAME.strip("'\" ") if KAGGLE_USERNAME else ""

    try:
        # Establish configuration directory
        kaggle_dir = os.path.expanduser("~/.kaggle")
        os.makedirs(kaggle_dir, exist_ok=True)
        
        # Force the CLI to read directly from this folder path
        os.environ['KAGGLE_CONFIG_DIR'] = kaggle_dir

        # 💡 FIX 1: Set ALL environment standards together (No more exclusive if/else)
        if clean_username:
            os.environ['KAGGLE_USERNAME'] = clean_username
        os.environ['KAGGLE_KEY'] = clean_key
        os.environ['KAGGLEAPITOKEN'] = clean_key  # Direct injection for new CLI v2

        # 💡 FIX 2: Create the legacy kaggle.json file
        if clean_username:
            credentials = {"username": clean_username, "key": clean_key}
            config_path = os.path.join(kaggle_dir, "kaggle.json")
            with open(config_path, "w") as f:
                json.dump(credentials, f)
            os.chmod(config_path, 0o600)

        # 💡 FIX 3: Create the modern standalone accesstoken file
        token_path = os.path.join(kaggle_dir, "accesstoken")
        with open(token_path, "w") as f:
            f.write(clean_key)
        os.chmod(token_path, 0o600)

        print("✅ All legacy and modern Kaggle credentials synchronized to disk and environment successfully.")
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
        # 💡 FIX 4: Explicitly pass env=os.environ so the subprocess inherits the keys
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