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
# 2. AUTOMATED REPAIR & FIXES
# ==========================================
def setup_kaggle_credentials():
    """Configures the classic Kaggle CLI credentials folder layout."""
    if not KAGGLE_KEY or not KAGGLE_USERNAME:
        print("⚠️ Kaggle credentials missing from Render environment variables!")
        return

    clean_username = KAGGLE_USERNAME.strip("'\" \n\r")
    clean_key = KAGGLE_KEY.strip("'\" \n\r")

    try:
        kaggle_dir = "/opt/render/.kaggle"
        os.makedirs(kaggle_dir, exist_ok=True)
        
        os.environ['KAGGLE_CONFIG_DIR'] = kaggle_dir
        os.environ['KAGGLE_USERNAME'] = clean_username
        os.environ['KAGGLE_KEY'] = clean_key

        config_path = os.path.join(kaggle_dir, "kaggle.json")
        credentials = {"username": clean_username, "key": clean_key}
        with open(config_path, "w") as f:
            json.dump(credentials, f)
        os.chmod(config_path, 0o600)
        
        print(f"✅ Successfully built kaggle.json at {config_path}")
        
        # Run local repository fixes
        fix_metadata_username(clean_username)
        fix_notebook_kernelspec()

    except Exception as e:
        print(f"❌ Failed to set up Kaggle credentials: {e}")


def fix_metadata_username(clean_username):
    """Ensures kernel-metadata.json relies on your active username."""
    metadata_path = "./notebook_folder/kernel-metadata.json"
    if os.path.exists(metadata_path):
        try:
            with open(metadata_path, "r") as f:
                data = json.load(f)
            
            current_id = data.get("id", "")
            if "/" in current_id:
                meta_user, slug = current_id.split("/", 1)
                if meta_user != clean_username:
                    data["id"] = f"{clean_username}/{slug}"
                    with open(metadata_path, "w") as f:
                        json.dump(data, f, indent=4)
            else:
                data["id"] = f"{clean_username}/{current_id}"
                with open(metadata_path, "w") as f:
                    json.dump(data, f, indent=4)
        except Exception as e:
            print(f"⚠️ Metadata username sync skipped: {e}")


def fix_notebook_kernelspec():
    """🎯 AUTO-FIX: Inspects the notebook file and embeds missing Python 3 environment metadata."""
    metadata_path = "./notebook_folder/kernel-metadata.json"
    if not os.path.exists(metadata_path):
        return

    try:
        with open(metadata_path, "r") as f:
            meta_data = json.load(f)
        
        code_file_name = meta_data.get("code_file", "")
        kernel_type = meta_data.get("kernel_type", "notebook")
        
        # Only inject if the project uses an actual notebook (.ipynb file)
        if kernel_type == "notebook" and code_file_name.endswith(".ipynb"):
            notebook_path = os.path.join("./notebook_folder", code_file_name)
            
            if os.path.exists(notebook_path):
                try:
                    with open(notebook_path, "r") as f:
                        nb_data = json.load(f)
                except (json.JSONDecodeError, ValueError):
                    # If file is completely empty or corrupted, create clean notebook shell boilerplate
                    nb_data = {"cells": [], "metadata": {}, "nbformat": 4, "nbformat_minor": 2}
                
                if "metadata" not in nb_data:
                    nb_data["metadata"] = {}
                
                # If kernelspec metadata is missing, inject standard Python 3 runtime structures
                if "kernelspec" not in nb_data["metadata"] or not nb_data["metadata"]["kernelspec"]:
                    print(f"🛠️ Embedding missing Python 3 environment metadata stamp into {code_file_name}")
                    nb_data["metadata"]["kernelspec"] = {
                        "display_name": "Python 3",
                        "language": "python",
                        "name": "python3"
                    }
                    if "language_info" not in nb_data["metadata"]:
                        nb_data["metadata"]["language_info"] = {"name": "python"}
                        
                    with open(notebook_path, "w") as f:
                        json.dump(nb_data, f, indent=4)
            else:
                print(f"⚠️ Notebook source target file '{code_file_name}' not found at {notebook_path}")
    except Exception as e:
        print(f"⚠️ Notebook environmental metadata fix skipped: {e}")


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
    
    # Run fixes again directly before pushing to ensure any local workspace runtime edits align
    setup_kaggle_credentials()
    
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