import os
import cv2
import numpy as np
import pytesseract
import subprocess
import threading
import time
from PIL import Image, ImageDraw, ImageFont
from flask import Flask, render_template_string, jsonify
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, CallbackQueryHandler, ContextTypes

# ==========================================
# TESSERACT PATH
# ==========================================
if os.name == 'nt':  # Windows
    pytesseract.pytesseract.tesseract_cmd = r'C:\Tesseract-OCR\tesseract.exe'
else:  # Linux (Render / Docker)
    pytesseract.pytesseract.tesseract_cmd = '/usr/bin/tesseract'

# ==========================================
# GLOBAL VARIABLES
# ==========================================
user_brands = {}
bot_logs = []
bot_start_time = time.time()
last_command = "None"

def log_message(msg):
    timestamp = time.strftime("%H:%M:%S")
    bot_logs.append(f"[{timestamp}] {msg}")
    if len(bot_logs) > 50:
        bot_logs.pop(0)
    print(msg)

# ==========================================
# 🎉 START COMMAND
# ==========================================
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_id = user.id
    brand_status = f"✅ Your current brand: **{user_brands[user_id]}**" if user_id in user_brands else "❌ No brand set yet."
    welcome_message = (
        f"👋 **Hello {user.first_name}!**\n\n"
        f"🤖 I am your **Smart Brand Text Remover Bot**.\n"
        f"I detect your old watermark and replace it with your brand!\n\n"
        f"📌 **How to use me:**\n"
        f"1️⃣ Set your brand: `/setbrand t.me/yourchannel`\n"
        f"2️⃣ Upload a photo or video.\n"
        f"3️⃣ I will detect, erase, and add **your brand**!\n\n"
        f"{brand_status}\n\n"
        f"🚀 **Ready to start?** Upload a photo or video below!"
    )
    keyboard = [[InlineKeyboardButton("📸 Upload Media", switch_inline_query="")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(welcome_message, parse_mode='Markdown', reply_markup=reply_markup)
    log_message(f"👤 User {user_id} started the bot")

# ==========================================
# BOT COMMANDS
# ==========================================
async def set_brand(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = ' '.join(context.args)
    if not text:
        await update.message.reply_text("❌ **Usage:** `/setbrand YourBrandName`\nExample: `/setbrand t.me/mychannel`", parse_mode='Markdown')
        return
    user_brands[user_id] = text
    log_message(f"👤 User {user_id} set brand: {text}")
    await update.message.reply_text(f"✅ **Brand saved successfully!**\n\n`{text}`\n\nNow upload a photo or video to apply it.", parse_mode='Markdown')

async def handle_media(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in user_brands:
        await update.message.reply_text("⚠️ **Please set your brand first!**\nUse `/setbrand t.me/yourchannel`", parse_mode='Markdown')
        return

    brand_text = user_brands[user_id]
    message = update.message
    log_message(f"📤 User {user_id} uploaded {'Video' if message.video else 'Photo'}")

    if message.media_group_id:
        if 'albums' not in context.bot_data:
            context.bot_data['albums'] = {}
        album_id = message.media_group_id
        if album_id not in context.bot_data['albums']:
            context.bot_data['albums'][album_id] = {'user_id': user_id, 'files': [], 'brand': brand_text}
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
        await message.reply_text("Please send a photo or video.")
        return

    base_name = f"{user_id}_{message.message_id}_{message.date.timestamp()}"
    input_path = f"{base_name}_input{ext}"
    output_path = f"{base_name}_output{ext}"

    try:
        status_msg = await message.reply_text(f"⏳ **Processing {media_type}...**\n🔍 Smart scanning for text...", parse_mode='Markdown')
        await file.download_to_drive(input_path)
        
        if media_type == "photo":
            hybrid_smart_photo_removal(input_path, output_path, brand_text)
            await status_msg.delete()
            await message.reply_photo(photo=open(output_path, 'rb'))
        else:
            hybrid_smart_video_removal(input_path, output_path, brand_text)
            await status_msg.delete()
            await message.reply_video(video=open(output_path, 'rb'))
            
    except Exception as e:
        log_message(f"❌ Error: {e}")
        await message.reply_text(f"❌ **Error:** {e}", parse_mode='Markdown')
    finally:
        for path in [input_path, output_path]:
            if os.path.exists(path): os.remove(path)

async def process_album(update: Update, context: ContextTypes.DEFAULT_TYPE):
    album_id = update.message.media_group_id
    if 'albums' not in context.bot_data: return
    album_data = context.bot_data['albums'].pop(album_id, None)
    if not album_data: return

    user_id = album_data['user_id']
    brand_text = album_data['brand']
    messages = album_data['files']
    log_message(f"📦 Processing Album with {len(messages)} files")
    status_msg = await update.message.reply_text(f"📦 **Album detected!**\nProcessing {len(messages)} files...", parse_mode='Markdown')

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
        
        base_name = f"album_{album_id}_{user_id}_{idx}"
        input_path = f"{base_name}_input{ext}"
        output_path = f"{base_name}_output{ext}"
        
        try:
            await file.download_to_drive(input_path)
            if media_type == "photo":
                hybrid_smart_photo_removal(input_path, output_path, brand_text)
                output_media.append({'type': 'photo', 'media': open(output_path, 'rb')})
            else:
                hybrid_smart_video_removal(input_path, output_path, brand_text)
                output_media.append({'type': 'video', 'media': open(output_path, 'rb')})
        except Exception as e:
            log_message(f"❌ Album Error: {e}")
        finally:
            if os.path.exists(input_path): os.remove(input_path)

    if output_media:
        await status_msg.delete()
        await update.message.reply_media_group(media=output_media)
        for item in output_media:
            if os.path.exists(item['media'].name): os.remove(item['media'].name)

# ==========================================
# 🔥 HYBRID SMART DETECTION + ERASE (BEST QUALITY)
# ==========================================

def hybrid_smart_photo_removal(input_path, output_path, new_text):
    img = cv2.imread(input_path)
    h, w, _ = img.shape

    # 1. CROP THE BOTTOM 30% ONLY (This stops it from seeing "1mo" at the top)
    crop_bottom = int(h * 0.30)
    bottom_half = img[h - crop_bottom:h, 0:w]
    
    # 2. DETECT TEXT ONLY IN THE BOTTOM CROP
    gray = cv2.cvtColor(bottom_half, cv2.COLOR_BGR2GRAY)
    _, thresh = cv2.threshold(gray, 150, 255, cv2.THRESH_BINARY_INV)
    data = pytesseract.image_to_data(thresh, output_type=pytesseract.Output.DICT)
    
    mask = np.zeros((h, w), dtype=np.uint8)
    detected_coords = None
    found = False

    for i in range(len(data['text'])):
        if int(data['conf'][i]) > 30:
            text = data['text'][i].strip()
            if text:
                # Adjust coordinates back to the full image
                x = data['left'][i]
                y = data['top'][i] + (h - crop_bottom)
                w_box = data['width'][i]
                h_box = data['height'][i]
                
                # Expand box to fully cover text
                padding = 15
                x = max(0, x - padding)
                y = max(0, y - padding)
                w_box = min(w - x, w_box + padding*2)
                h_box = min(h - y, h_box + padding*2)
                
                mask[y:y+h_box, x:x+w_box] = 255
                detected_coords = (x, y, w_box, h_box)
                found = True
                log_message(f"✅ Detected text '{text}' at {x},{y}")
                break # Only take the first/largest text found

    # 3. FALLBACK: If no text found, use bottom-right corner
    if not found:
        log_message("⚠️ No text found in bottom 30%, using bottom-right default.")
        x = w - 400
        y = h - 100
        detected_coords = (x, y, 400, 100)
        mask[y:y+100, x:x+400] = 255

    # 4. AI INPAINTING TO ERASE TEXT
    cleaned_img = cv2.inpaint(img, mask, 5, cv2.INPAINT_TELEA)

    # 5. ADD NEW TEXT AT EXACT DETECTED POSITION
    pil_img = Image.fromarray(cv2.cvtColor(cleaned_img, cv2.COLOR_BGR2RGB))
    draw = ImageDraw.Draw(pil_img)
    
    try:
        font_size = int(min(h, w) * 0.04)
        font = ImageFont.truetype("arial.ttf", font_size)
    except:
        font = ImageFont.load_default()
        
    bbox = draw.textbbox((0, 0), new_text, font=font)
    text_w = bbox[2] - bbox[0]
    text_h = bbox[3] - bbox[1]

    x, y, old_w, old_h = detected_coords
    # Center the text inside the detected box
    center_x = x + (old_w // 2) - (text_w // 2)
    center_y = y + (old_h // 2) - (text_h // 2)

    draw.rectangle([center_x-10, center_y-10, center_x+text_w+10, center_y+text_h+10], fill=(0,0,0,180))
    draw.text((center_x, center_y), new_text, font=font, fill="white")
    pil_img.save(output_path)

def hybrid_smart_video_removal(input_path, output_path, new_text):
    cap = cv2.VideoCapture(input_path)
    ret, first_frame = cap.read()
    cap.release()
    if not ret:
        raise Exception("Could not read video")
        
    h, w, _ = first_frame.shape
    
    # 1. SCAN BOTTOM 30% OF FIRST FRAME ONLY
    crop_bottom = int(h * 0.30)
    bottom_half = first_frame[h - crop_bottom:h, 0:w]
    gray = cv2.cvtColor(bottom_half, cv2.COLOR_BGR2GRAY)
    _, thresh = cv2.threshold(gray, 150, 255, cv2.THRESH_BINARY_INV)
    data = pytesseract.image_to_data(thresh, output_type=pytesseract.Output.DICT)
    
    coords = None
    for i in range(len(data['text'])):
        if int(data['conf'][i]) > 30:
            text = data['text'][i].strip()
            if text:
                x = data['left'][i]
                y = data['top'][i] + (h - crop_bottom)
                w_box = data['width'][i]
                h_box = data['height'][i]
                coords = (x, y, w_box, h_box)
                log_message(f"🎥 Video detected text '{text}'")
                break
    
    if not coords:
        log_message("⚠️ Video: No text found, using bottom-right default.")
        coords = (w-400, h-100, 400, 100)
    
    x, y, w_box, h_box = coords
    safe_text = new_text.replace("'", r"\'").replace(":", r"\:")
    
    x_perc = x / w
    y_perc = y / h
    w_perc = w_box / w
    h_perc = h_box / h

    # 2. PATCH + ADD NEW TEXT
    filter_complex = (
        f"[0:v]drawbox=w={w_perc}*iw:h={h_perc}*ih:x={x_perc}*iw:y={y_perc}*ih:color=black:t=fill[erased];"
        f"[erased]drawtext=text='{safe_text}':"
        f"fontcolor=white:fontsize=35:"
        f"box=1:boxcolor=black@0.5:boxborderw=10:"
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

# ==========================================
# 🎨 FLASK DASHBOARD UI
# ==========================================
app_web = Flask(__name__)

HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>🤖 Brand Bot Dashboard</title>
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
        .footer a { color: #3b82f6; text-decoration: none; }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>🤖 Brand Text Remover Bot</h1>
            <div><span class="status-badge">🟢 Online</span></div>
        </div>
        <div class="stats-grid">
            <div class="stat-card">
                <h3>Uptime</h3>
                <div class="value">{{ uptime }}</div>
            </div>
            <div class="stat-card">
                <h3>Total Users</h3>
                <div class="value">{{ users }}</div>
            </div>
            <div class="stat-card">
                <h3>Last Command</h3>
                <div class="value" style="font-size: 16px; color: #facc15;">{{ last_cmd }}</div>
            </div>
        </div>
        <div class="logs-container">
            <div class="logs-header">
                <h2>📋 Live Activity Logs</h2>
                <button class="refresh-btn" onclick="location.reload()">🔄 Refresh</button>
            </div>
            <div class="logs-box" id="logBox">
                {% for log in logs %}
                <div class="log-entry">
                    <span class="log-time">{{ log }}</span>
                </div>
                {% endfor %}
            </div>
        </div>
        <div class="footer">
            Built with ❤️ 
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
        users=len(user_brands),
        last_cmd=last_command,
        logs=bot_logs.copy()
    )

def run_flask():
    app_web.run(host='0.0.0.0', port=10000)

# ==========================================
# MAIN ENTRY POINT
# ==========================================
if __name__ == "__main__":
    TOKEN = os.environ.get("BOT_TOKEN")
    if not TOKEN:
        log_message("❌ Error: BOT_TOKEN environment variable is not set!")
        exit(1)

    threading.Thread(target=run_flask, daemon=True).start()
    log_message("🌐 Dashboard started on port 10000")

    application = Application.builder().token(TOKEN).build()
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("setbrand", set_brand))
    application.add_handler(MessageHandler(filters.PHOTO | filters.VIDEO, handle_media))
    application.add_handler(MessageHandler(filters.PHOTO | filters.VIDEO, process_album), group=1)
    
    log_message("🤖 Smart Hybrid Bot started successfully!")
    application.run_polling()
