import os
import cv2
import gc
import numpy as np
import pytesseract
import subprocess
import threading
import time
import asyncio
import shutil
from PIL import Image, ImageDraw, ImageFont
from flask import Flask, render_template_string, jsonify
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# ==========================================
# 🧹 BACKGROUND CACHE CLEANER THREAD
# ==========================================
def cache_cleaner():
    """Runs in background every 30 minutes to delete __pycache__ folders"""
    while True:
        time.sleep(1800)
        try:
            current_dir = os.getcwd()
            for root, dirs, files in os.walk(current_dir):
                for dir_name in dirs:
                    if dir_name == "__pycache__":
                        pycache_path = os.path.join(root, dir_name)
                        shutil.rmtree(pycache_path, ignore_errors=True)
                        print(f"🧹 Cleaned cache folder: {pycache_path}")
        except Exception as e:
            print(f"⚠️ Cache cleaner error: {e}")

threading.Thread(target=cache_cleaner, daemon=True).start()
print("🧹 Disk Cache Cleaner thread started")

# ==========================================
# GLOBAL VARIABLES
# ==========================================
bot_start_time = time.time()
last_command = "None"
active_users = set()
bot_logs = []
user_processing_lock = {}  # To prevent duplicate uploads from same user

def log_message(msg):
    timestamp = time.strftime("%H:%M:%S")
    log_line = f"[{timestamp}] {msg}"
    print(log_line)
    bot_logs.append(log_line)
    if len(bot_logs) > 50:
        bot_logs.pop(0)

# ==========================================
# 📋 HELP COMMAND
# ==========================================
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = (
        "🛠️ **Bot Commands Guide**\n\n"
        "`/start` - Welcome message & status\n"
        "`/help` - Show this help menu\n"
        "`/setbrand <text>` - Save your brand name\n"
        "   Example: `/setbrand t.me/mychannel`\n"
        "`/mybrand` - Check your current saved brand\n"
        "`/clearbrand` - Delete your saved brand\n"
        "`/cancel` - Cancel your current processing (if stuck)\n\n"
        "📤 **Upload:** Send a photo or video to apply your brand automatically!"
    )
    await update.message.reply_text(help_text, parse_mode='Markdown')

# ==========================================
# 🎉 START COMMAND
# ==========================================
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_id = user.id
    active_users.add(user_id)
    
    brand = context.user_data.get('brand', None)
    brand_status = f"✅ Your brand: **{brand}**" if brand else "❌ No brand set. Use `/setbrand`"
    
    welcome_message = (
        f"👋 **Hello {user.first_name}!**\n\n"
        f"🤖 **Ultimate Watermark Remover Bot**\n"
        f"✓ Multi text support\n"
        f"✓ Auto-cache cleaning\n"
        f"✓ Blue Icon detection\n\n"
        f"📌 **Status:**\n{brand_status}\n\n"
        f"📖 Type `/help` to see all commands!\n"
        f"🚀 **Upload a media file below!**"
    )
    keyboard = [[InlineKeyboardButton("📸 Upload Media", switch_inline_query="")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(welcome_message, parse_mode='Markdown', reply_markup=reply_markup)
    log_message(f"👤 User {user_id} started the bot")

# ==========================================
# 💼 BRAND MANAGEMENT COMMANDS
# ==========================================
async def set_brand(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = ' '.join(context.args)
    if not text:
        await update.message.reply_text("❌ **Usage:** `/setbrand YourBrandName`", parse_mode='Markdown')
        return
    
    context.user_data['brand'] = text
    active_users.add(user_id)
    log_message(f"👤 User {user_id} set brand: {text}")
    await update.message.reply_text(f"✅ **Brand saved!**\n\n`{text}`\n\nUpload your media now.", parse_mode='Markdown')

async def my_brand(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    brand = context.user_data.get('brand', None)
    if brand:
        await update.message.reply_text(f"✅ **Your current brand is:**\n`{brand}`", parse_mode='Markdown')
    else:
        await update.message.reply_text("❌ You haven't set a brand yet.\nUse `/setbrand YourBrandName`", parse_mode='Markdown')

async def clear_brand(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if 'brand' in context.user_data:
        del context.user_data['brand']
        log_message(f"👤 User {user_id} cleared their brand")
        await update.message.reply_text("✅ **Brand cleared!** You can set a new one with `/setbrand`", parse_mode='Markdown')
    else:
        await update.message.reply_text("ℹ️ You don't have a brand set to clear.", parse_mode='Markdown')

async def cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    # Future feature: If you implement a queue, you can cancel the user's task here
    await update.message.reply_text("⏹️ **Cancelled any ongoing process.** (If you had one)", parse_mode='Markdown')

# ==========================================
# 📤 MEDIA HANDLER
# ==========================================
async def handle_media(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    brand_text = context.user_data.get('brand', None)
    
    if not brand_text:
        await update.message.reply_text("⚠️ **Set your brand first!**\nUse `/setbrand YourBrandName`", parse_mode='Markdown')
        return

    message = update.message
    active_users.add(user_id)
    log_message(f"📤 User {user_id} uploaded {'Video' if message.video else 'Photo'}")

    # Check file size limit (Telegram max = 2GB = 2000MB)
    file_size = None
    if message.video:
        file_size = message.video.file_size
    elif message.photo:
        file_size = message.photo[-1].file_size
    
    if file_size and file_size > 2000 * 1024 * 1024:  # 2GB limit
        await message.reply_text("❌ File is too large! Telegram limit is 150mb.")
        return

    if message.media_group_id:
        if 'albums' not in context.bot_data:
            context.bot_data['albums'] = {}
        album_id = message.media_group_id
        if album_id not in context.bot_data['albums']:
            context.bot_data['albums'][album_id] = {'user_id': user_id, 'files': []}
        context.bot_data['albums'][album_id]['files'].append(message)
    else:
        await process_single_file(update, context, user_id, brand_text, message)

async def process_single_file(update, context, user_id, brand_text, message):
    file = None
    ext = ""
    media_type = ""

    if message.video:
        file = await message.video.get_file()
        ext = ".mp4"
        media_type = "video"
    elif message.photo:
        file = await message.photo[-1].get_file()
        ext = ".jpg"
        media_type = "photo"
    else:
        return

    unique_id = f"{user_id}_{int(time.time() * 1000)}"
    input_path = f"{unique_id}_input{ext}"
    output_path = f"{unique_id}_output{ext}"

    try:
        status_msg = await message.reply_text(f"⏳ **Processing {media_type}...**", parse_mode='Markdown')
        await file.download_to_drive(input_path)
        
        if media_type == "photo":
            pixel_perfect_removal(input_path, output_path, brand_text)
            await status_msg.delete()
            await message.reply_photo(photo=open(output_path, 'rb'))
        else:
            # Video progress simulation (just a status update)
            await status_msg.edit_text(f"⏳ **Processing Video...**\n🎬 Detecting Watermark ..")
            pixel_perfect_video_removal(input_path, output_path, brand_text)
            await status_msg.delete()
            await message.reply_video(video=open(output_path, 'rb'))
            
    except Exception as e:
        log_message(f"❌ Error for User {user_id}: {e}")
        await message.reply_text(f"❌ **Error:** {e}\n\nTry uploading a smaller file or clearing your brand with `/clearbrand` and trying again.", parse_mode='Markdown')
    finally:
        for path in [input_path, output_path]:
            if os.path.exists(path): 
                try:
                    os.remove(path)
                except:
                    pass
        cv2.destroyAllWindows()
        gc.collect()

async def process_album(update: Update, context: ContextTypes.DEFAULT_TYPE):
    album_id = update.message.media_group_id
    if 'albums' not in context.bot_data: return
    album_data = context.bot_data['albums'].pop(album_id, None)
    if not album_data: return

    user_id = album_data['user_id']
    brand_text = context.user_data.get('brand', None)
    if not brand_text: return

    messages = album_data['files']
    log_message(f"📦 Processing Album with {len(messages)} files for User {user_id}")
    status_msg = await update.message.reply_text(f"📦 **it takes time go and take shower!**\nProcessing {len(messages)} files...", parse_mode='Markdown')

    output_media = []
    for idx, message in enumerate(messages):
        file = None
        ext = ""
        media_type = ""
        if message.video:
            file = await message.video.get_file()
            ext = ".mp4"
            media_type = "video"
        elif message.photo:
            file = await message.photo[-1].get_file()
            ext = ".jpg"
            media_type = "photo"
        
        unique_id = f"album_{album_id}_{user_id}_{idx}"
        input_path = f"{unique_id}_input{ext}"
        output_path = f"{unique_id}_output{ext}"
        
        try:
            await file.download_to_drive(input_path)
            if media_type == "photo":
                pixel_perfect_removal(input_path, output_path, brand_text)
                output_media.append({'type': 'photo', 'media': open(output_path, 'rb')})
            else:
                pixel_perfect_video_removal(input_path, output_path, brand_text)
                output_media.append({'type': 'video', 'media': open(output_path, 'rb')})
        except Exception as e:
            log_message(f"❌ Album Error: {e}")
        finally:
            if os.path.exists(input_path): 
                try:
                    os.remove(input_path)
                except:
                    pass

    if output_media:
        await status_msg.delete()
        await update.message.reply_media_group(media=output_media)
        for item in output_media:
            if os.path.exists(item['media'].name): 
                try:
                    os.remove(item['media'].name)
                except:
                    pass

    cv2.destroyAllWindows()
    gc.collect()

# ==========================================
# 🎯 PIXEL-PERFECT REMOVAL
# ==========================================
def pixel_perfect_removal(input_path, output_path, new_text):
    img = cv2.imread(input_path)
    h, w, _ = img.shape

    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    lower_blue = np.array([95, 100, 100])
    upper_blue = np.array([125, 255, 255])
    mask = cv2.inRange(hsv, lower_blue, upper_blue)
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    
    detected_coords = None
    
    if contours:
        largest_contour = max(contours, key=cv2.contourArea)
        x, y, w_box, h_box = cv2.boundingRect(largest_contour)
        expand_right = int(w_box * 2.5)
        padding = 10
        x = max(0, x - padding)
        y = max(0, y - padding)
        w_box = min(w - x, w_box + expand_right + padding)
        h_box = min(h - y, h_box + padding * 2)
        detected_coords = (x, y, w_box, h_box)
        
    else:
        # Fallback text detection
        crop_bottom = int(h * 0.30)
        bottom_half = img[h - crop_bottom:h, 0:w]
        gray = cv2.cvtColor(bottom_half, cv2.COLOR_BGR2GRAY)
        _, thresh = cv2.threshold(gray, 150, 255, cv2.THRESH_BINARY_INV)
        data = pytesseract.image_to_data(thresh, output_type=pytesseract.Output.DICT)
        
        for i in range(len(data['text'])):
            if int(data['conf'][i]) > 30:
                text = data['text'][i].strip()
                if text:
                    x = data['left'][i]
                    y = data['top'][i] + (h - crop_bottom)
                    w_box = data['width'][i]
                    h_box = data['height'][i]
                    padding = 15
                    x = max(0, x - padding)
                    y = max(0, y - padding)
                    w_box = min(w - x, w_box + padding*2)
                    h_box = min(h - y, h_box + padding*2)
                    detected_coords = (x, y, w_box, h_box)
                    break

    if not detected_coords:
        x = w - 400
        y = h - 100
        detected_coords = (x, y, 400, 100)

    x, y, w_box, h_box = detected_coords
    inpaint_mask = np.zeros((h, w), dtype=np.uint8)
    inpaint_mask[y:y+h_box, x:x+w_box] = 255

    cleaned_img = cv2.inpaint(img, inpaint_mask, 5, cv2.INPAINT_TELEA)

    pil_img = Image.fromarray(cv2.cvtColor(cleaned_img, cv2.COLOR_BGR2RGB))
    draw = ImageDraw.Draw(pil_img)
    
    font_size = int(min(h, w) * 0.04)
    try:
        font = ImageFont.truetype("arialbd.ttf", font_size)
    except:
        font = ImageFont.load_default()
        
    bbox = draw.textbbox((0, 0), new_text, font=font)
    text_w = bbox[2] - bbox[0]
    text_h = bbox[3] - bbox[1]

    center_x = x + (w_box // 2) - (text_w // 2)
    center_y = y + (h_box // 2) - (text_h // 2)

    draw.text((center_x, center_y), new_text, font=font, fill="white")
    pil_img.save(output_path)
    
    del img, cleaned_img, pil_img, draw
    gc.collect()

def pixel_perfect_video_removal(input_path, output_path, new_text):
    cap = cv2.VideoCapture(input_path)
    ret, first_frame = cap.read()
    
    if not ret:
        cap.release()
        raise Exception("Could not read video")
        
    h, w, _ = first_frame.shape
    safe_text = new_text.replace("'", r"\'").replace(":", r"\:")
    
    hsv = cv2.cvtColor(first_frame, cv2.COLOR_BGR2HSV)
    lower_blue = np.array([95, 100, 100])
    upper_blue = np.array([125, 255, 255])
    mask = cv2.inRange(hsv, lower_blue, upper_blue)
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    
    x, y, w_box, h_box = 0, 0, 0, 0
    
    if contours:
        largest_contour = max(contours, key=cv2.contourArea)
        x, y, w_box, h_box = cv2.boundingRect(largest_contour)
        expand_right = int(w_box * 2.5)
        x = max(0, x - 10)
        y = max(0, y - 10)
        w_box = min(w - x, w_box + expand_right + 10)
        h_box = min(h - y, h_box + 20)
    else:
        x = w - 400
        y = h - 100
        w_box = 400
        h_box = 100
    
    cap.release()
    first_frame = None
    
    x_perc = x / w
    y_perc = y / h
    w_perc = w_box / w
    h_perc = h_box / h

    filter_complex = (
        f"[0:v]drawbox=w={w_perc}*iw:h={h_perc}*ih:x={x_perc}*iw:y={y_perc}*ih:color=black:t=fill[erased];"
        f"[erased]drawtext=text='{safe_text}':"
        f"fontcolor=yellow:fontsize=35:"
        f"box=1:boxcolor=black@0.5:boxborderw=10:"
        f"fontfile=/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf:"
        f"x={x}:y={y}[out]"
    )
    
    cmd = [
        "ffmpeg", "-i", input_path,
        "-filter_complex", filter_complex,
        "-map", "[out]",
        "-map", "0:a?",
        "-c:a", "copy",
        "-preset", "fast",
        "-y", output_path
    ]
    subprocess.run(cmd, check=True)
    gc.collect()

# ==========================================
# 🎨 FLASK DASHBOARD
# ==========================================
app_web = Flask(__name__)

HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>🤖 Ultimate Brand Bot</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; }
        body { background: #0f172a; color: #e2e8f0; padding: 20px; }
        .container { max-width: 1200px; margin: 0 auto; }
        .header { background: #1e293b; padding: 25px; border-radius: 16px; margin-bottom: 25px; border-left: 5px solid #3b82f6; display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; }
        .header h1 { font-size: 28px; display: flex; align-items: center; gap: 12px; }
        .status-badge { background: #22c55e; padding: 6px 16px; border-radius: 20px; font-size: 14px; font-weight: 600; color: #fff; }
        .stats-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 15px; margin-bottom: 25px; }
        .stat-card { background: #1e293b; padding: 20px; border-radius: 12px; text-align: center; }
        .stat-card h3 { color: #94a3b8; font-size: 14px; text-transform: uppercase; letter-spacing: 1px; }
        .stat-card .value { font-size: 28px; font-weight: 700; color: #3b82f6; margin-top: 8px; }
        .logs-container { background: #1e293b; border-radius: 16px; padding: 20px; }
        .logs-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 15px; }
        .logs-header h2 { font-size: 20px; }
        .logs-box { background: #0f172a; border-radius: 8px; padding: 15px; height: 400px; overflow-y: auto; font-family: 'Courier New', monospace; font-size: 14px; border: 1px solid #334155; }
        .log-entry { padding: 4px 0; border-bottom: 1px solid #1e293b; }
        .log-time { color: #64748b; margin-right: 10px; }
        .log-msg { color: #e2e8f0; }
        .refresh-btn { background: #3b82f6; border: none; color: white; padding: 8px 20px; border-radius: 8px; cursor: pointer; font-weight: 600; transition: 0.2s; }
        .refresh-btn:hover { background: #2563eb; }
        .footer { text-align: center; margin-top: 25px; color: #64748b; font-size: 14px; }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>🤖 Watermark Remover Bot</h1>
            <div><span class="status-badge">🟢 Online</span></div>
        </div>
        <div class="stats-grid">
            <div class="stat-card"><h3>Uptime</h3><div class="value">{{ uptime }}</div></div>
            <div class="stat-card"><h3>Active Users</h3><div class="value">{{ users }}</div></div>
            <div class="stat-card"><h3>Last Command</h3><div class="value" style="font-size: 16px; color: #facc15;">{{ last_cmd }}</div></div>
        </div>
        <div class="logs-container">
            <div class="logs-header"><h2>📋 Live Logs</h2><button class="refresh-btn" onclick="location.reload()">🔄 Refresh</button></div>
            <div class="logs-box">{% for log in logs %}<div class="log-entry"><span class="log-time">{{ log }}</span></div>{% endfor %}</div>
        </div>
    </div>
</body>
</html>
"""

@app_web.route('/')
def dashboard():
    uptime_seconds = int(time.time() - bot_start_time)
    hours = uptime_seconds // 3600
    minutes = (uptime_seconds % 3600) // 60
    uptime_str = f"{hours}h {minutes}m"
    return render_template_string(
        HTML_TEMPLATE,
        uptime=uptime_str,
        users=len(active_users),
        last_cmd=last_command,
        logs=bot_logs.copy()
    )

def run_flask():
    app_web.run(host='0.0.0.0', port=10000)

# ==========================================
# MAIN
# ==========================================
if __name__ == "__main__":
    TOKEN = os.environ.get("BOT_TOKEN")
    if not TOKEN:
        log_message("❌ Error: BOT_TOKEN missing!")
        exit(1)

    threading.Thread(target=run_flask, daemon=True).start()

    application = Application.builder().token(TOKEN).build()
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("setbrand", set_brand))
    application.add_handler(CommandHandler("mybrand", my_brand))
    application.add_handler(CommandHandler("clearbrand", clear_brand))
    application.add_handler(CommandHandler("cancel", cancel_command))
    application.add_handler(MessageHandler(filters.PHOTO | filters.VIDEO, handle_media))
    application.add_handler(MessageHandler(filters.PHOTO | filters.VIDEO, process_album), group=1)
    
    log_message("🤖 Ultimate Brand Bot started successfully! (Full feature set)")
    
    application.run_polling()
