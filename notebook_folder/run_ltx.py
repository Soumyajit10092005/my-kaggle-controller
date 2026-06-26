%%writefile run_ltx.py
import gc
import os
import sys
import time
import json
import random
import tempfile
import glob
import traceback
import threading
import numpy as np
import subprocess
import psutil
from PIL import Image

print("🚀 [Kaggle] run_ltx.py started...")

# ====================== EARLY CONFIRMATION ======================
try:
    from kaggle_secrets import UserSecretsClient
    import telebot
    from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
    
    BOT_TOKEN = UserSecretsClient().get_secret("TELEGRAM_BOT_TOKEN")
    bot = telebot.TeleBot(BOT_TOKEN)
    CHAT_ID = 1972666456   # ← Your personal chat ID

    bot.send_message(CHAT_ID, 
        "⚡ **Kaggle Video Bot is ONLINE!**\n\n"
        "✅ Successfully started on Kaggle GPU.\n"
        "🔄 Loading heavy LTX model (this may take 8-15 minutes)...\n"
        "You will get another message when model is ready.", 
        parse_mode="Markdown")
    print("✅ Early confirmation message sent!")
except Exception as e:
    print(f"❌ Early confirmation failed: {e}")
    traceback.print_exc()

# ====================== HEAVY MODEL LOADING ======================
print("🔄 Starting Wan2GP + LTX Model Loading...")

try:
    # Thread safe logging
    class ThreadSafeMuter:
        def __init__(self, original_stream):
            self.original_stream = original_stream
            self.muted_threads = set()
        def write(self, data):
            if threading.get_ident() in self.muted_threads: return
            self.original_stream.write(data)
        def flush(self):
            try: self.original_stream.flush()
            except: pass

    sys.stdout = ThreadSafeMuter(sys.stdout)
    sys.stderr = ThreadSafeMuter(sys.stderr)

    # Bootstrap
    WAN2GP_DIR = os.path.abspath("Wan2GP")
    sys.path.insert(0, WAN2GP_DIR)
    os.chdir(WAN2GP_DIR)
    os.environ["PYTORCH_ALLOC_CONF"] = "expandable_segments:True,max_split_size_mb:128,garbage_collection_threshold:0.5"
    os.environ["TOKENIZERS_PARALLELISM"] = "false"

    # Hotpatch
    ltx2_path = os.path.join(WAN2GP_DIR, "models/ltx2/ltx2.py")
    if os.path.exists(ltx2_path):
        with open(ltx2_path, "r") as f:
            content = f.read()
        old_line = "input_video_strength = max(0.0, min(1.0, input_video_strength))"
        new_line = "input_video_strength = max(0.0, min(1.0, input_video_strength)) if input_video_strength is not None else 1.0"
        if old_line in content:
            content = content.replace(old_line, new_line)
            with open(ltx2_path, "w") as f:
                f.write(content)
            print("✅ LTX2 Bug Patched!")
print("Script started")

bot.send_message(
    1972666456,
    "✅ Kaggle runtime has started. Initializing models..."
)
    import torch
    from shared.utils.audio_video import save_video

    print(f"GPU: {torch.cuda.get_device_name()}")
    print(f"VRAM: {torch.cuda.get_device_properties(0).total_memory / 1024**3:.1f} GB")

    # Model Loading (your original code)
    from mmgp import offload
    from shared.utils import files_locator as fl
    fl.set_checkpoints_paths(["models", "ckpts", "."])
    from models.ltx2.ltx2_handler import family_handler

    base_model_type = "ltx2_22B"
    model_def = {"ltx2_pipeline": "distilled"}
    extra = family_handler.query_model_def(base_model_type, model_def)
    model_def.update(extra)

    gemma_folder = "models/gemma-3-12b-it-qat-q4_0-unquantized"
    gemma_files = sorted(glob.glob(os.path.join(gemma_folder, "*.safetensors")))
    quanto_files = [f for f in gemma_files if "quanto" in f]
    text_encoder_file = quanto_files[0] if quanto_files else (gemma_files[0] if gemma_files else None)

    transformer_path = os.path.join("models", "ltx-2.3-22b-distilled_diffusion_model_quanto_int8.safetensors")

    ltx2_model, pipe = family_handler.load_model(
        model_filename=transformer_path,
        model_type="ltx2_22B_distilled",
        base_model_type=base_model_type,
        model_def=model_def,
        dtype=torch.bfloat16,
        VAE_dtype=torch.float32,
        text_encoder_filename=text_encoder_file,
    )

    offload.profile(pipe, profile_no=4, quantizeTransformer=False, convertWeightsFloatTo=torch.bfloat16, budgets={
        "transformer": 7000, "text_encoder": 1500, "vae": 2500,
        "spatial_upsampler": 1500, "video_encoder": 1500, "*": 500,
    })
    offload.shared_state["_attention"] = "sdpa"
    print("✅ Model Loaded Successfully!")

    bot.send_message(CHAT_ID, "✅ **Model Loaded!** Bot is fully ready.\nSend `/start` to begin.", parse_mode="Markdown")

except Exception as e:
    print(f"❌ Error during loading: {e}")
    traceback.print_exc()
    try:
        bot.send_message(CHAT_ID, "❌ Model loading failed. Check Kaggle logs.", parse_mode="Markdown")
    except:
        pass

# ==== TELEGRAM CORE FRAMEWORK ENGINE ====
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
from kaggle_secrets import UserSecretsClient

BOT_TOKEN = UserSecretsClient().get_secret("TELEGRAM_BOT_TOKEN")
bot = telebot.TeleBot(BOT_TOKEN)

USER_CONFIGS = {}
IS_GENERATING = False
STATE_LOCK = threading.Lock()

def get_user_state(chat_id):
    if chat_id not in USER_CONFIGS:
        USER_CONFIGS[chat_id] = {"duration": "3s", "resolution": "720p"}
    return USER_CONFIGS[chat_id]

# 🔥 FEATURE 2: KILL COMMAND FOR SYSTEM RUNTIME TERMINATION
@bot.message_handler(commands=['exit'])
def terminate_environment(message):
    try:
        bot.reply_to(
            message, 
            "🛑 **Shutdown Command Executed!**\n"
            "Stopping the Telegram Bot listener matrix and terminating the Kaggle execution runtime environment completely... Goodbye!"
        )
        time.sleep(2)
    except:
        pass
    print("\n[System Alert] Exit code triggered via Telegram client interface. Killing active runtime.")
    sys.stdout.flush()
    os._exit(0)  # Hard kill ensures all background dependencies and current execution cell completely drops

@bot.message_handler(commands=['start', 'generate'])
def start_wizard(message):
    chat_id = message.chat.id
    USER_CONFIGS[chat_id] = {"duration": "3s", "resolution": "720p"}
    
    markup = InlineKeyboardMarkup(row_width=3)
    markup.add(
        InlineKeyboardButton("3 Sec", callback_data="dur_3s"),
        InlineKeyboardButton("5 Sec", callback_data="dur_5s"),
        InlineKeyboardButton("10 Sec", callback_data="dur_10s"),
        InlineKeyboardButton("15 Sec", callback_data="dur_15s"),
        InlineKeyboardButton("20 Sec", callback_data="dur_20s")
    )
    bot.send_message(chat_id, "🎬 **Step 1: Choose Video Duration**", reply_markup=markup, parse_mode="Markdown")

@bot.callback_query_handler(func=lambda call: call.data.startswith('dur_'))
def handle_duration(call):
    chat_id = call.message.chat.id
    selected_duration = call.data.split('_')[1]
    get_user_state(chat_id)["duration"] = selected_duration
    
    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(
        InlineKeyboardButton("720p (Max HD Quality)", callback_data="res_720p"),
        InlineKeyboardButton("480p (Fast Processing)", callback_data="res_480p")
    )
    bot.edit_message_text(f"⏱️ Duration set to: **{selected_duration}**\n\n**Step 2: Choose Quality Target**", 
                          chat_id, call.message.message_id, reply_markup=markup, parse_mode="Markdown")

@bot.callback_query_handler(func=lambda call: call.data.startswith('res_'))
def handle_resolution(call):
    chat_id = call.message.chat.id
    selected_res = call.data.split('_')[1]
    state = get_user_state(chat_id)
    state["resolution"] = selected_res
    
    bot.edit_message_text(
        f"⚙️ **Configuration Locked Successfully!**\n"
        f"• Duration: `{state['duration']}`\n"
        f"• Aspect Ratio: `Auto-Adapts to Image Aspect Proportions`\n"
        f"• Default Seed Setup: `Random (-1)`\n\n"
        f"👇 **Final Step:**\n"
        f"Now send me your text prompt directly OR upload an image with your prompt typed inside its description box.",
        chat_id, call.message.message_id, parse_mode="Markdown"
    )

def execute_pipeline(chat_id, prompt_text, raw_image_path=None):
    print("[System Process] Secure Creation Pipeline Initialized...")
    sys.stdout.flush()
    
    status_msg = bot.send_message(chat_id, "⏳ Initializing hardware layers...")
    state = get_user_state(chat_id)
    
    # Wrapped safely to ensure temporary network dropouts don't crash the background process
    def update_status(text):
        try: bot.edit_message_text(text, chat_id, status_msg.message_id, parse_mode="Markdown")
        except: pass

    output_video, status = Video_Generation(
        prompt=prompt_text,
        input_image_start=raw_image_path,
        duration_dropdown=state["duration"],
        resolution_dropdown=state["resolution"],
        telegram_callback=update_status
    )
    
    if output_video and os.path.exists(output_video):
        try: bot.edit_message_text("📤 Delivering processing payload safely...", chat_id, status_msg.message_id)
        except: pass
        with open(output_video, 'rb') as f:
            bot.send_video(chat_id, f, caption="✨ **Render Complete!**", parse_mode="Markdown")
        try: bot.delete_message(chat_id, status_msg.message_id)
        except: pass
    else:
        bot.send_message(chat_id, f"❌ Hardware Processing Error:\n`{status}`", parse_mode="Markdown")

    # SANITIZATION PROTOCOL
    time.sleep(3) 
    if raw_image_path and os.path.exists(raw_image_path):
        try: os.remove(raw_image_path)
        except: pass

    for target_dir in ['/tmp', '/kaggle/working/Wan2GP', '/kaggle/working']:
        if os.path.exists(target_dir):
            for entry in os.listdir(target_dir):
                full_path = os.path.join(target_dir, entry)
                if entry.endswith(('.mp4', '.jpg', '.jpeg', '.png', '.wav', '.tmp')):
                    try:
                        if os.path.isfile(full_path): os.remove(full_path)
                    except: pass
                    
    USER_CONFIGS[chat_id] = {"duration": "3s", "resolution": "720p"}
    gc.collect()
    torch.cuda.empty_cache()
    print("[System Process] Secure Data Purged. Storage Workspace Completely Cleared.")
    sys.stdout.flush()

def async_pipeline_router(chat_id, prompt_text, raw_image_path=None):
    global IS_GENERATING
    with STATE_LOCK:
        if IS_GENERATING:
            bot.send_message(chat_id, "⚠️ **System Busy:** Another video generation is currently processing in the background. Please wait a moment before sending a new request!", parse_mode="Markdown")
            if raw_image_path and os.path.exists(raw_image_path):
                try: os.remove(raw_image_path)
                except: pass
            return
        IS_GENERATING = True

    # 🔥 FEATURE 1: Background worker keeps running even if the browser/screen goes to sleep
    worker_thread = threading.Thread(target=lambda: execute_pipeline_worker())
    
    def execute_pipeline_worker():
        global IS_GENERATING
        try:
            execute_pipeline(chat_id, prompt_text, raw_image_path)
        finally:
            with STATE_LOCK:
                IS_GENERATING = False

    worker_thread.start()

@bot.message_handler(content_types=['photo'])
def process_image_input(message):
    if not message.caption:
        bot.reply_to(message, "⚠️ Error: You must include your description text prompt directly inside the image caption box before hitting send.")
        return
    file_info = bot.get_file(message.photo[-1].file_id)
    local_img_path = f"/tmp/tgt_frame_{message.message_id}.jpg"
    with open(local_img_path, 'wb') as f:
        f.write(bot.download_file(file_info.file_path))
    async_pipeline_router(message.chat.id, message.caption, local_img_path)

@bot.message_handler(content_types=['text'])
def process_text_input(message):
    if message.text.startswith('/'): return
    async_pipeline_router(message.chat.id, message.text, None)

print("\n📡 Connection successfully established with Telegram! Bot is now online.")
sys.stdout.flush()

print("📡 Bot is ready and listening...")
sys.stdout.flush()

try:
    bot.infinity_polling(timeout=90, long_polling_timeout=90)
except Exception as e:
    print(f"Polling error: {e}")
    traceback.print_exc()
# Added broad long_polling timeouts to tolerate extended connection sleep/idling periods seamlessly
bot.infinity_polling(timeout=90, long_polling_timeout=90)