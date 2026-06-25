import os
import json
import time
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
# 2. AUTOMATED REPAIR & METADATA UTILITIES
# ==========================================
def setup_kaggle_credentials():
    """Configures the classic Kaggle CLI credentials layout."""
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
        
        # Apply corrections
        fix_metadata_username(clean_username)
        fix_notebook_kernelspec()

    except Exception as e:
        print(f"❌ Failed to set up Kaggle credentials: {e}")


def fix_metadata_username(clean_username):
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
    metadata_path = "./notebook_folder/kernel-metadata.json"
    if not os.path.exists(metadata_path):
        return
    try:
        with open(metadata_path, "r") as f:
            meta_data = json.load(f)
        code_file_name = meta_data.get("code_file", "")
        if meta_data.get("kernel_type", "notebook") == "notebook" and code_file_name.endswith(".ipynb"):
            notebook_path = os.path.join("./notebook_folder", code_file_name)
            if os.path.exists(notebook_path):
                try:
                    with open(notebook_path, "r") as f:
                        nb_data = json.load(f)
                except:
                    nb_data = {"cells": [], "metadata": {}, "nbformat": 4, "nbformat_minor": 2}
                
                if "metadata" not in nb_data:
                    nb_data["metadata"] = {}
                if "kernelspec" not in nb_data["metadata"] or not nb_data["metadata"]["kernelspec"]:
                    nb_data["metadata"]["kernelspec"] = {
                        "display_name": "Python 3", "language": "python", "name": "python3"
                    }
                    with open(notebook_path, "w") as f:
                        json.dump(nb_data, f, indent=4)
    except Exception as e:
        print(f"⚠️ Notebook metadata fix skipped: {e}")


def get_kernel_id():
    """Reads the current active kernel identifier string from metadata."""
    try:
        with open("./notebook_folder/kernel-metadata.json", "r") as f:
            return json.load(f).get("id", "")
    except:
        return ""


# ==========================================
# 3. LIVE BACKGROUND PROGRESS TRACKER
# ==========================================
def track_kaggle_progress(chat_id, status_msg_id, kernel_id):
    """Polls Kaggle API periodically and updates the Telegram UI message."""
    if not kernel_id:
        bot.edit_message_text("❌ Tracking failed: Could not determine Kernel ID.", chat_id, status_msg_id)
        return

    print(f"🔄 Starting background tracking loop for kernel: {kernel_id}")
    start_time = time.time()
    last_status = ""
    
    # Maximum timeout protection (e.g., 20 minutes)
    while (time.time() - start_time) < 1200:
        time.sleep(15)  # Poll every 15 seconds safely
        
        result = subprocess.run(
            ["kaggle", "kernels", "status", kernel_id],
            capture_output=True, text=True, env=os.environ
        )
        
        output = result.stdout.lower() + result.stderr.lower()
        
        # Parse Kaggle status outputs
        if "queued" in output:
            status, bar, details = "Queued", "░░░░░░░░░░ 0%", "⏳ Waiting for an available Kaggle GPU cluster node..."
        elif "running" in output:
            status, bar, details = "Running", "▓▓▓▓░░░░░░ 40%", "⚙️ Running code cells & generating artifacts..."
        elif "complete" in output:
            status, bar, details = "Complete", "▓▓▓▓▓▓▓▓▓▓ 100%", "🏁 Job finished successfully! Check output folders."
            ui_text = f"🟩 **Kaggle Server Status: {status}**\n`[{bar}]`\n\n{details}"
            bot.edit_message_text(ui_text, chat_id, status_msg_id, parse_mode="Markdown")
            break
        elif "error" in output or "failed" in output:
            status, bar, details = "Failed", "██████████ CRASH", "❌ Internal code execution crashed inside the notebook."
            ui_text = f"🟥 **Kaggle Server Status: {status}**\n`[{bar}]`\n\n{details}\n👉 Check your Kaggle panel logs for traceback."
            bot.edit_message_text(ui_text, chat_id, status_msg_id, parse_mode="Markdown")
            break
        else:
            status, bar, details = "Unknown", "░░░░░░░░░░ ??%", "Connecting to Kaggle telemetry stream..."

        # Update message only if status text changes to minimize rate-limiting
        ui_text = f"🟨 **Kaggle Server Status: {status}**\n`[{bar}]`\n\n{details}\n⏱️ Elapsed time: {int(time.time() - start_time)}s"
        if ui_text != last_status:
            try:
                bot.edit_message_text(ui_text, chat_id, status_msg_id, parse_mode="Markdown")
                last_status = ui_text
            except Exception:
                pass


# ==========================================
# 4. FLASK WEB ROUTING
# ==========================================
@app.route('/')
def home():
    return "⚡ Kaggle Controller Node is Online"


# ==========================================
# 5. TELEGRAM BOT EVENT HANDLERS
# ==========================================
@bot.message_handler(commands=['ready'])
def trigger_kaggle_instance(message):
    chat_id = message.chat.id
    status_msg = bot.send_message(chat_id, "🚀 Synchronizing keys and sending runtime payload to Kaggle...")
    
    setup_kaggle_credentials()
    
    try:
        result = subprocess.run(
            ["kaggle", "kernels", "push", "-p", "./notebook_folder"], 
            capture_output=True, text=True, env=os.environ  
        )
        
        if result.returncode == 0:
            kernel_id = get_kernel_id()
            bot.edit_message_text(
                f"📡 **Payload Delivered Successfully!**\n\nStarting telemetry tracking engine for `{kernel_id}`...",
                chat_id, status_msg.message_id
            )
            # Spin up the background telemetry worker thread
            threading.Thread(
                target=track_kaggle_progress, 
                args=(chat_id, status_msg.message_id, kernel_id), 
                daemon=True
            ).start()
        else:
            stderr_lines = result.stderr.splitlines()
            filtered_errors = [line for line in stderr_lines if "SyntaxWarning" not in line and "site-packages/kaggle" not in line]
            real_error = "\n".join(filtered_errors).strip() or result.stdout.strip()
            clean_error = real_error.replace("`", "").replace("*", "").replace("_", "")
            bot.edit_message_text(f"❌ *Kaggle API Handshake Refused*:\n\n```\n{clean_error}\n```", chat_id, status_msg.message_id, parse_mode="Markdown")
            
    except Exception as e:
        bot.send_message(chat_id, f"❌ Controller Exception:\n`{str(e)}`", parse_mode="Markdown")


# ==========================================
# 6. EXECUTION ROUTERS
# ==========================================
def run_tg_bot():
    try:
        bot.delete_webhook(drop_pending_updates=True)
    except:
        pass
    print("📡 Starting Telegram listener loop...")
    bot.infinity_polling()


if __name__ == "__main__":
    setup_kaggle_credentials()
    threading.Thread(target=run_tg_bot, daemon=True).start()
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)