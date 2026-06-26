import os
import json
import time
import threading
import subprocess
from flask import Flask
import telebot
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
NOTEBOOK_DIR = os.path.join(BASE_DIR, "notebook_folder")
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
    print("=" * 50)
    print("BOT_TOKEN:", BOT_TOKEN is not None)
    print("KAGGLE_USERNAME:", repr(KAGGLE_USERNAME))
    print("KAGGLE_KEY exists:", KAGGLE_KEY is not None)
    print("=" * 50)
    """Configures the classic Kaggle CLI credentials layout."""
    if not KAGGLE_KEY or not KAGGLE_USERNAME:
        print("⚠️ Kaggle credentials missing from Render environment variables!")
        return False

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
        fix_notebook_and_cells()
        return True
    except Exception as e:
        print(f"❌ Failed to set up Kaggle credentials: {e}")
        return False

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


def fix_notebook_and_cells():
    """🎯 FIXED: Injects python3 environments AND ensures an execution cell runs the written script."""
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
                
                # Fix structural environment headers
                if "metadata" not in nb_data:
                    nb_data["metadata"] = {}
                if "kernelspec" not in nb_data["metadata"] or not nb_data["metadata"]["kernelspec"]:
                    nb_data["metadata"]["kernelspec"] = {
                        "display_name": "Python 3", "language": "python", "name": "python3"
                    }
                
                # Check cells to make sure it doesn't just save the file, but also EXECUTEs it
                cells = nb_data.get("cells", [])
                has_run_command = False
                for cell in cells:
                    source = cell.get("source", [])
                    source_str = "".join(source) if isinstance(source, list) else str(source)
                    if "python run_ltx.py" in source_str:
                        has_run_command = True
                        break
                
                if not has_run_command:
                    print("🛠️ Auto-injecting run trigger cell (!python run_ltx.py) into the notebook deployment pipeline...")
                    execution_cell = {
                        "cell_type": "code",
                        "execution_count": None,
                        "metadata": {},
                        "outputs": [],
                        "source": ["!python run_ltx.py"]
                    }
                    cells.append(execution_cell)
                    nb_data["cells"] = cells
                
                with open(notebook_path, "w") as f:
                    json.dump(nb_data, f, indent=4)
    except Exception as e:
        print(f"⚠️ Notebook structural repair skipped: {e}")


def get_kernel_id():
    try:
        with open("./notebook_folder/kernel-metadata.json", "r") as f:
            return json.load(f).get("id", "")
    except:
        return ""


# ==========================================
# 3. LIVE BACKGROUND PROGRESS TRACKER
# ==========================================
def track_kaggle_progress(chat_id, status_msg_id, kernel_id):
    if not kernel_id:
        bot.edit_message_text("❌ Tracking failed: Could not determine Kernel ID.", chat_id, status_msg_id)
        return

    print(f"🔄 Starting background tracking loop for kernel: {kernel_id}")
    start_time = time.time()
    last_status = ""
    
    while (time.time() - start_time) < 1200:
        time.sleep(15) 
        
        result = subprocess.run(
            ["kaggle", "kernels", "push", "-p", NOTEBOOK_DIR],
            capture_output=True,
            text=True,
            timeout=90,
            env=os.environ
        )
        print("=" * 60)
        print("RETURN CODE:", result.returncode)
        print("STDOUT:")
        print(result.stdout)
        print("STDERR:")
        print(result.stderr)
        print("=" * 60)
        output = result.stdout.lower() + result.stderr.lower()
        
        if "queued" in output:
            status, bar, details = "Queued", "░░░░░░░░░░ 0%", "⏳ Waiting for an available Kaggle GPU cluster node..."
            ui_text = f"🟨 **Kaggle Server Status: {status}**\n`[{bar}]`\n\n{details}\n⏱️ Elapsed time: {int(time.time() - start_time)}s"
        elif "running" in output:
            status, bar, details = "Running", "▓▓▓▓░░░░░░ 40%", "⚙️ Engine Online! Running code cells, spinning up Telegram dependencies, and mounting VRAM..."
            ui_text = f"🟦 **Kaggle Server Status: {status}**\n`[{bar}]`\n\n{details}\n⏱️ Elapsed time: {int(time.time() - start_time)}s\n\n👉 *Keep an eye on your video bot conversation for the welcome message!*"
        elif "complete" in output:
            status, bar, details = "Complete", "▓▓▓▓▓▓▓▓▓▓ 100%", "🏁 Instance runtime closed cleanly or user terminated via /exit command."
            ui_text = f"🟩 **Kaggle Server Status: {status}**\n`[{bar}]`\n\n{details}"
            bot.edit_message_text(ui_text, chat_id, status_msg_id, parse_mode="Markdown")
            break
        elif "error" in output or "failed" in output:
            status, bar, details = "Failed", "██████████ CRASH", "❌ Internal code execution crashed inside the notebook engine."
            ui_text = f"🟥 **Kaggle Server Status: {status}**\n`[{bar}]`\n\n{details}\n👉 Check your Kaggle panel web UI console to read Python exceptions."
            bot.edit_message_text(ui_text, chat_id, status_msg_id, parse_mode="Markdown")
            break
        else:
            status, bar, details = "Unknown", "░░░░░░░░░░ ??%", "Connecting to Kaggle telemetry stream..."
            ui_text = f"🟨 **Kaggle Server Status: {status}**\n`[{bar}]`\n\n{details}"

        if ui_text != last_status:
            try:
                bot.edit_message_text(ui_text, chat_id, status_msg_id, parse_mode="Markdown")
                last_status = ui_text
            except:
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
def handle_ready(message):
    chat_id = message.chat.id
    bot.reply_to(message, "🚀 **Waking up Kaggle Notebook...**")
    
    if not setup_kaggle_credentials():
        bot.send_message(chat_id, "❌ Kaggle credentials missing!")
        return
    
    threading.Thread(target=push_and_run_notebook, args=(chat_id,), daemon=True).start()

def push_and_run_notebook(chat_id):
    try:
        status_msg = bot.send_message(chat_id, "📤 Pushing notebook to Kaggle...")

        # Update kernel metadata username
        metadata_path = os.path.join(NOTEBOOK_DIR, "kernel-metadata.json")
        if os.path.exists(metadata_path):
            with open(metadata_path, "r") as f:
                meta = json.load(f)
            if not meta.get("id", "").startswith(f"{KAGGLE_USERNAME}/"):
                slug = meta.get("id", "").split("/")[-1] or "ltx-video-bot"
                meta["id"] = f"{KAGGLE_USERNAME}/{slug}"
                with open(metadata_path, "w") as f:
                    json.dump(meta, f, indent=4)

        # Push + Run
        result = subprocess.run(
            ["kaggle", "kernels", "push", "-p", NOTEBOOK_DIR],
            capture_output=True, text=True, timeout=300
        )

        if result.returncode != 0:
            bot.edit_message_text(f"❌ Push failed:\n{result.stderr[:500]}", chat_id, status_msg.message_id)
            return

        kernel_id = get_kernel_id()
        bot.edit_message_text(f"✅ **Notebook pushed & running!**\nKernel: `{kernel_id}`\n\nWaiting for confirmation from Kaggle Bot...", 
                            chat_id, status_msg.message_id, parse_mode="Markdown")

        # Optional: start tracking
        threading.Thread(target=track_kaggle_progress, args=(chat_id, status_msg.message_id, kernel_id), daemon=True).start()

    except Exception as e:
        bot.send_message(chat_id, f"❌ Error waking Kaggle: {str(e)}")

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