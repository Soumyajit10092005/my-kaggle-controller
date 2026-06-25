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

# ==== THREAD-ISOLATED LOG ISOLATION ENGINE ====
class ThreadSafeMuter:
    def __init__(self, original_stream):
        self.original_stream = original_stream
        self.muted_threads = set()
    def write(self, data):
        if threading.get_ident() in self.muted_threads:
            return
        self.original_stream.write(data)
    def flush(self):
        try: self.original_stream.flush()
        except: pass

sys.stdout = ThreadSafeMuter(sys.stdout)
sys.stderr = ThreadSafeMuter(sys.stderr)

class HideCurrentThreadLogs:
    def __enter__(self):
        current_id = threading.get_ident()
        if hasattr(sys.stdout, "muted_threads"): sys.stdout.muted_threads.add(current_id)
        if hasattr(sys.stderr, "muted_threads"): sys.stderr.muted_threads.add(current_id)
    def __exit__(self, exc_type, exc_val, exc_tb):
        current_id = threading.get_ident()
        if hasattr(sys.stdout, "muted_threads"): sys.stdout.muted_threads.discard(current_id)
        if hasattr(sys.stderr, "muted_threads"): sys.stderr.muted_threads.discard(current_id)

# ---- bootstrap Wan2GP ----
WAN2GP_DIR = os.path.abspath("Wan2GP")
sys.path.insert(0, WAN2GP_DIR)
os.chdir(WAN2GP_DIR)
os.environ["PYTORCH_ALLOC_CONF"] = "expandable_segments:True,max_split_size_mb:128,garbage_collection_threshold:0.5"
os.environ["TOKENIZERS_PARALLELISM"] = "false"

# ==== HOTPATCH THE LTX2 INTERNAL ENGINE BUG ====
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
        print("✅ Core Engine Bug Patched Successfully inside ltx2.py!")
sys.stdout.flush()

import torch
from shared.utils.audio_video import save_video

# ==== GPU & SYSTEM INFO ====
print(f"GPU Engine Status: {torch.cuda.get_device_name()}")
print(f"Total Available VRAM: {torch.cuda.get_device_properties(0).total_memory / 1024**3:.1f} GB")
sys.stdout.flush()

# ==== Core Backend Opts ====
torch.backends.cuda.enable_flash_sdp(False)
torch.backends.cuda.enable_mem_efficient_sdp(True)
torch.backends.cuda.enable_math_sdp(True)

# ==== LOAD TRANSFORMATION PIPELINE ====
print("\n[Engine Initialization] Loading LTX-2.3 Model Matrix into VRAM...")
sys.stdout.flush()

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

# ==== Apply mmgp Budget Allocation Profile 4 ====
offload.profile(
    pipe,
    profile_no=4,
    quantizeTransformer=False,
    convertWeightsFloatTo=torch.bfloat16,
    budgets={
        "transformer":  7000,
        "text_encoder": 1500,
        "vae":          2500,
        "spatial_upsampler": 1500,
        "video_encoder": 1500,
        "*":             500,
    },
)
offload.shared_state["_attention"] = "sdpa"
print("✅ Hardware Layer Allocation Mapping Complete!")
sys.stdout.flush()

# ==== METRIC PROCESSING RESOLUTION PARSERS ====
def get_resolution(base_res_str, aspect_ratio_str):
    if base_res_str == "720p":
        return 1024, 576  
    else:
        return 512, 288   

def get_vae_tile_size(height, width):
    return (256, 3) if max(height, width) > 480 else (0, 1)

@torch.inference_mode()
def Video_Generation(prompt, input_image_start, duration_dropdown, resolution_dropdown, telegram_callback=None):
    try:
        gc.collect()
        torch.cuda.empty_cache()

        duration_map = {
            "3s": 73, "5s": 121, "10s": 241, "15s": 361, "20s": 481
        }
        num_frames = duration_map.get(duration_dropdown, 73)
        seed = random.randint(0, 2**32 - 1)

        image_start = None
        if input_image_start and os.path.exists(input_image_start):
            src_img = Image.open(input_image_start).convert("RGB")
            src_w, src_h = src_img.size
            
            max_side = 1024 if resolution_dropdown == "720p" else 768
            if max(src_w, src_h) > max_side:
                scale = max_side / max(src_w, src_h)
                src_w = int(src_w * scale)
                src_h = int(src_h * scale)
            
            width = (src_w // 32) * 32
            height = (src_h // 32) * 32
            width = max(128, width)
            height = max(128, height)
            
            image_start = src_img.resize((width, height), Image.Resampling.LANCZOS)
            print(f"[Image Config] Active canvas dimension: {width}x{height}")
            sys.stdout.flush()
        else:
            width, height = get_resolution(resolution_dropdown, "16:9 Landscape")

        vae_tile_size, _ = get_vae_tile_size(height, width)
        total_steps = [8]
        current_step = [0]
        current_pass = [1]
        last_update_time = [0.0]

        def cb(step, latent, is_start, override_num_inference_steps=None, pass_no=None, **kwargs):
            if is_start:
                if override_num_inference_steps is not None: total_steps[0] = override_num_inference_steps
                if pass_no is not None: current_pass[0] = pass_no
                current_step[0] = 0
                return
            current_step[0] += 1
            frac = current_step[0] / max(total_steps[0], 1)
            actual_percent = int((0.7 * frac * 100) if current_pass[0] == 1 else ((0.7 + 0.3 * frac) * 100))
            if actual_percent > 100: actual_percent = 100
            
            now = time.time()
            if telegram_callback and (now - last_update_time[0] >= 2.5 or actual_percent >= 98):
                last_update_time[0] = now
                blocks = min(10, max(0, int(actual_percent / 10)))
                bar_graphic = "█" * blocks + "░" * (10 - blocks)
                stage_name = "Drafting Structure" if current_pass[0] == 1 else "Polishing Details"
                
                progress_ui = (
                    f"🎬 **Generation Progress:** `{actual_percent}%` Complete\n"
                    f"`[{bar_graphic}]`\n"
                    f"⚡ **Stage:** `{stage_name}`\n"
                    f"⏳ *Steps remaining:* `{max(0, total_steps[0] - current_step[0])}`"
                )
                telegram_callback(progress_ui)

        gen_kwargs = dict(
            input_prompt=prompt, image_start=image_start, height=height, width=width,
            frame_num=num_frames, fps=24.0, seed=seed, callback=cb,
            VAE_tile_size=vae_tile_size, enhance_prompt=True,
            input_video_strength=1.0
        )

        with HideCurrentThreadLogs():
            result = ltx2_model.generate(**gen_kwargs)
            
        if result is None: return None, "Processing failed."
        video_tensor = result.get("x") if isinstance(result, dict) else (result[0] if isinstance(result[0], tuple) else result)
        video_tensor = video_tensor.cpu()
        
        out_path = tempfile.mktemp(suffix=".mp4")
        video_for_save = (video_tensor.unsqueeze(0).float() / 127.5) - 1.0
        
        with HideCurrentThreadLogs():
            save_video(tensor=video_for_save, save_file=out_path, fps=24.0, normalize=True, value_range=(-1, 1))
        return out_path, "Success"

    except Exception as e:
        return None, str(e)

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

# Added broad long_polling timeouts to tolerate extended connection sleep/idling periods seamlessly
bot.infinity_polling(timeout=90, long_polling_timeout=90)