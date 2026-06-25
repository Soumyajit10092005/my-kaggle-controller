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
    """Configures system variables dynamically based on token type."""
    if not KAGGLE_KEY:
        print("⚠️ Kaggle API Key/Token environment variable is missing. Skipping setup.")
        return

    clean_key = KAGGLE_KEY.strip("'\" \n\r")
    
    try:
        kaggle_dir = os.path.expanduser("~/.kaggle")
        os.makedirs(kaggle_dir, exist_ok=True)
        os.environ['KAGGLE_CONFIG_DIR'] = kaggle_dir

        # Wipe out old physical files to prevent stale credential mixing
        for stale_file in ["kaggle.json", "accesstoken"]:
            stale_path = os.path.join(kaggle_dir, stale_file)
            if os.path.exists(stale_path):
                os.remove(stale_path)

        # 🎯 AUTO-DETECTION LOGIC FOR MODERN TOKENS
        if clean_key.startswith("KGAT_"):
            print("👁️ Modern standalone 'KGAT' token detected. Activating isolated Token authentication.")
            
            # Completely strip legacy environment footprints that cause conflicts
            os.environ.pop('KAGGLE_USERNAME', None)
            os.environ.pop('KAGGLE_KEY', None)
            
            # Apply modern credential properties exclusively
            os.environ['KAGGLEAPITOKEN'] = clean_key
            
            token_path = os.path.join(kaggle_dir, "accesstoken")
            with open(token_path, "w") as f:
                f.write(clean_key)
            os.chmod(token_path, 0o600)
            
        else:
            print("👁️ Classic key format detected. Activating standard Username+Key pairing.")
            clean_username = KAGGLE_USERNAME.strip("'\" \n\r") if KAGGLE_USERNAME else ""
            
            os.environ['KAGGLE_USERNAME'] = clean_username
            os.environ['KAGGLE_KEY'] = clean_key
            os.environ.pop('KAGGLEAPITOKEN', None)
            
            if clean_username:
                credentials = {"username": clean_username, "key": clean_key}
                config_path = os.path.join(kaggle_dir, "kaggle.json")
                with open(config_path, "w") as f:
                    json.dump(credentials, f)
                os.chmod(config_path, 0o600)

        print("✅ Credentials structural configuration synchronized successfully.")
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
            stderr_lines = result.stderr.splitlines()
            filtered_errors = [
                line for line in stderr_lines 
                if "SyntaxWarning" not in line and "site-packages/kaggle" not in line
            ]
            
            real_error = "\n".join(filtered_errors).strip()
            if not real_error:
                real_error = result.stdout.strip() or f"Unknown execution fault (Exit Code: {result.returncode})"
            
            clean_error = real_error.replace("`", "").replace("*", "").replace("_", "")
            bot.send_message(chat_id, f"❌ *Kaggle API Handshake Refused*:\n\n```\n{clean_error}\n```", parse_mode="Markdown")
            
    except Exception as e:
        bot.send_message(chat_id, f"❌ Controller Exception:\n`{str(e)}`", parse_mode="Markdown")


# ==========================================
# 5. EXECUTION ROUTERS
# ==========================================
def run_tg_bot():
    try:
        bot.delete_webhook(drop_pending_updates=True)
    except Exception as e:
        pass
    print("📡 Starting Telegram listener loop...")
    bot.infinity_polling()


if __name__ == "__main__":
    setup_kaggle_credentials()
    threading.Thread(target=run_tg_bot, daemon=True).start()
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)