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
    """Configures the classic Kaggle CLI to look exactly where Render expects it."""
    if not KAGGLE_KEY or not KAGGLE_USERNAME:
        print("⚠️ Kaggle credentials missing from Render environment variables!")
        return

    clean_username = KAGGLE_USERNAME.strip("'\" \n\r")
    clean_key = KAGGLE_KEY.strip("'\" \n\r")

    try:
        # Render's log explicitly asks for this exact path: /opt/render/.kaggle
        kaggle_dir = "/opt/render/.kaggle"
        os.makedirs(kaggle_dir, exist_ok=True)
        
        # Inject directly into environment variables
        os.environ['KAGGLE_CONFIG_DIR'] = kaggle_dir
        os.environ['KAGGLE_USERNAME'] = clean_username
        os.environ['KAGGLE_KEY'] = clean_key

        # Create the standard kaggle.json file
        config_path = os.path.join(kaggle_dir, "kaggle.json")
        credentials = {"username": clean_username, "key": clean_key}
        with open(config_path, "w") as f:
            json.dump(credentials, f)
        os.chmod(config_path, 0o600)
        
        print(f"✅ Successfully built kaggle.json at {config_path}")
        
        # 🎯 AUTO-FIX: Ensure kernel-metadata.json matches your username to prevent 401/403 errors
        fix_metadata_username(clean_username)

    except Exception as e:
        print(f"❌ Failed to set up Kaggle credentials: {e}")


def fix_metadata_username(clean_username):
    """Checks the notebook folder configuration and forces it to use your active username."""
    metadata_path = "./notebook_folder/kernel-metadata.json"
    if os.path.exists(metadata_path):
        try:
            with open(metadata_path, "r") as f:
                data = json.load(f)
            
            current_id = data.get("id", "")
            if "/" in current_id:
                meta_user, slug = current_id.split("/", 1)
                if meta_user != clean_username:
                    print(f"✏️ Auto-correcting metadata username from '{meta_user}' to '{clean_username}'")
                    data["id"] = f"{clean_username}/{slug}"
                    with open(metadata_path, "w") as f:
                        json.dump(data, f, indent=4)
            else:
                data["id"] = f"{clean_username}/{current_id}"
                with open(metadata_path, "w") as f:
                    json.dump(data, f, indent=4)
        except Exception as e:
            print(f"⚠️ Metadata auto-fix skipped: {e}")


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
            # Filter out Python 3.14 internal SyntaxWarnings to keep logs clean
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