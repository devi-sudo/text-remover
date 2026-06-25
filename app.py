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
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

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
    brand_status = f"✅ Your brand: **{user_brands[user_id]}**" if user_id in user_brands else "❌ No brand set."
    welcome_message = (
        f"👋 **Hello {user.first_name} !**\n\n"
        f"🤖 **WaterMark Rewrite Bot**\n"
        f"📌 **How to use:**\n"
        f"1️⃣ Set brand: `/setbrand YourBrandName`\n"
        f"2️⃣ Upload a photo or video.\n"
        f"3️⃣ Get a clean, professional result!\n\n"
        f"{brand_status}\n\n"
        f"🥹😂 **help - t.me/paid_promo0x**\n\n"
        f"🚀 **Upload a media file below!**"
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
        await update.message.reply_text("❌ **Usage:** `/setbrand YourBrandName`", parse_mode='Markdown')
        return
    user_brands[user_id] = text
    log_message(f"👤 User {user_id} set brand: {text}")
    await update.message.reply_text(f"✅ **Brand Name saved!**\n\n`{text}`\n\nUpload your media now.", parse_mode='Markdown')

async def handle_media(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in user_brands:
        await update.message.reply_text("⚠️ **Set your brand name first!**\nUse `/setbrand YourBrandName`", parse_mode='Markdown')
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
        return

    base_name = f"{user_id}_{message.message_id}_{int(time.time())}"
    input_path = f"{base_name}_input{ext}"
    output_path = f"{base_name}_output{ext}"

    try:
        status_msg = await message.reply_text(f"⏳\n\n **it Takes Time Go and take shower🚿**", parse_mode='Markdown')
        await file.download_to_drive(input_path)
        
        if media_type == "photo":
            pixel_perfect_removal(input_path, output_path, brand_text)
            await status_msg.delete()
            await message.reply_photo(photo=open(output_path, 'rb'))
        else:
            pixel_perfect_video_removal(input_path, output_path, brand_text)
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
    status_msg = await update.message.reply_text(f"👀 **OKY...?!**\nProcessing {len(messages)} \n\nIt Takes Time🥹\nDrink Water OR Coffee Daru 😂. \n i will done it shortly", parse_mode='Markdown')

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
                pixel_perfect_removal(input_path, output_path, brand_text)
                output_media.append({'type': 'photo', 'media': open(output_path, 'rb')})
            else:
                pixel_perfect_video_removal(input_path, output_path, brand_text)
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
# 🎯 PIXEL-PERFECT REMOVAL (Targets Blue Icon ONLY)
# ==========================================

def pixel_perfect_removal(input_path, output_path, new_text):
    img = cv2.imread(input_path)
    h, w, _ = img.shape

    # 1. CONVERT TO HSV TO FIND THE BLUE TELEGRAM ICON
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    
    # Define the exact blue color range of the Telegram icon
    lower_blue = np.array([95, 100, 100])
    upper_blue = np.array([125, 255, 255])
    
    # Create a mask where the blue icon is
    mask = cv2.inRange(hsv, lower_blue, upper_blue)
    
    # Find contours (outlines) of the blue icon
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    
    detected_coords = None
    
    if contours:
        # Find the largest blue object (which is the Telegram icon)
        largest_contour = max(contours, key=cv2.contourArea)
        x, y, w_box, h_box = cv2.boundingRect(largest_contour)
        
        log_message(f"✅ Found Blue Telegram Icon at ({x}, {y})")
        
        # 2. EXPAND THE BOX TO INCLUDE THE TEXT ON THE RIGHT
        # We expand width by 2.5x to capture the 't.me/...' text next to it
        expand_right = int(w_box * 2.5)
        padding = 10
        
        x = max(0, x - padding)
        y = max(0, y - padding)
        w_box = min(w - x, w_box + expand_right + padding)
        h_box = min(h - y, h_box + padding * 2)
        
        detected_coords = (x, y, w_box, h_box)
        log_message(f"✅ Expanded box to cover text. New area: {w_box}x{h_box}")
        
    else:
        # 3. FALLBACK: If no blue icon found, use Tesseract to scan for text
        log_message("⚠️ No blue icon found. Falling back to text detection in bottom half.")
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
                    log_message(f"✅ Fallback: Found text '{text}' at ({x}, {y})")
                    break

    # 4. IF NOTHING FOUND, USE A DEFAULT BOTTOM-RIGHT BOX
    if not detected_coords:
        log_message("⚠️ Nothing found. Using default bottom-right area.")
        x = w - 400
        y = h - 100
        detected_coords = (x, y, 400, 100)

    # 5. CREATE THE INPAINTING MASK
    x, y, w_box, h_box = detected_coords
    inpaint_mask = np.zeros((h, w), dtype=np.uint8)
    inpaint_mask[y:y+h_box, x:x+w_box] = 255

    # 6. AI INPAINT TO REMOVE THE ICON AND TEXT
    cleaned_img = cv2.inpaint(img, inpaint_mask, 5, cv2.INPAINT_TELEA)

    # 7. ADD NEW TEXT EXACTLY OVER THE REMOVED AREA (BOLD & ITALIC, NO BACKGROUND)
    pil_img = Image.fromarray(cv2.cvtColor(cleaned_img, cv2.COLOR_BGR2RGB))
    draw = ImageDraw.Draw(pil_img)
    
    # Set font size
    font_size = int(min(h, w) * 0.04)
    try:
        # Try to load Arial Bold
        font = ImageFont.truetype("arialbd.ttf", font_size)
        
        # Hack: PIL doesn't support true Italic natively. 
        # We apply a "pseudo-italic" by shearing the text.
        # But for clean brand marks, just Bold is usually enough.
        # To force Italic, we use a specific Italic font file if available.
        try:
            # Try Arial Italic for the italic look
            font = ImageFont.truetype("ariali.ttf", font_size)
        except:
            pass
    except:
        # Fallback to default font if arialbd.ttf is missing
        font = ImageFont.load_default()
        
    bbox = draw.textbbox((0, 0), new_text, font=font)
    text_w = bbox[2] - bbox[0]
    text_h = bbox[3] - bbox[1]

    # Center the new text perfectly inside the detected box
    center_x = x + (w_box // 2) - (text_w // 2)
    center_y = y + (h_box // 2) - (text_h // 2)

    # ❌ REMOVED THE BLACK BACKGROUND BOX
    # draw.rectangle([center_x-10, center_y-10, center_x+text_w+10, center_y+text_h+10], fill=(0,0,0,180))
    
    # Just draw the text directly in pure white (Bold)
    draw.text((center_x, center_y), new_text, font=font, fill="white")
    
    pil_img.save(output_path)

def pixel_perfect_video_removal(input_path, output_path, new_text):
    cap = cv2.VideoCapture(input_path)
    ret, first_frame = cap.read()
    cap.release()
    if not ret:
        raise Exception("Could not read video")
        
    h, w, _ = first_frame.shape
    safe_text = new_text.replace("'", r"\'").replace(":", r"\:")
    
    # 1. DETECT BLUE ICON ON THE FIRST FRAME
    hsv = cv2.cvtColor(first_frame, cv2.COLOR_BGR2HSV)
    lower_blue = np.array([95, 100, 100])
    upper_blue = np.array([125, 255, 255])
    mask = cv2.inRange(hsv, lower_blue, upper_blue)
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    
    x, y, w_box, h_box = 0, 0, 0, 0
    
    if contours:
        largest_contour = max(contours, key=cv2.contourArea)
        x, y, w_box, h_box = cv2.boundingRect(largest_contour)
        # Expand to cover text
        expand_right = int(w_box * 2.5)
        x = max(0, x - 10)
        y = max(0, y - 10)
        w_box = min(w - x, w_box + expand_right + 10)
        h_box = min(h - y, h_box + 20)
        log_message(f"🎥 Video: Found blue icon at ({x}, {y})")
    else:
        # Fallback to default bottom-right
        log_message("🎥 Video: No blue icon, using default area.")
        x = w - 400
        y = h - 100
        w_box = 400
        h_box = 100
    
    x_perc = x / w
    y_perc = y / h
    w_perc = w_box / w
    h_perc = h_box / h

    # 2. FFMPEG: Erase exact box + Add new text (No background, Bold Italic style)
    filter_complex = (
        f"[0:v]drawbox=w={w_perc}*iw:h={h_perc}*ih:x={x_perc}*iw:y={y_perc}*ih:color=black:t=fill[erased];"
        f"[erased]drawtext=text='{safe_text}':"
        f"fontcolor=white:fontsize=34:"
        f"fontfile=/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf:" # Try to load a bold font
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
# 🎨 FLASK DASHBOARD
# ==========================================
app_web = Flask(__name__)

HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>🤖 Pixel Bot</title>
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
            <h1>Branding Bot</h1>
            <p>free to use</p>
            <div><span class="status-badge">🟢 Online</span></div>
        </div>
        <div class="stats-grid">
            <div class="stat-card"><h3>Uptime</h3><div class="value">{{ uptime }}</div></div>
            <div class="stat-card"><h3>Total Users</h3><div class="value">{{ users }}</div></div>
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
        users=len(user_brands),
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
    log_message("🌐 Dashboard started on port 10000")

    application = Application.builder().token(TOKEN).build()
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("setbrand", set_brand))
    application.add_handler(MessageHandler(filters.PHOTO | filters.VIDEO, handle_media))
    application.add_handler(MessageHandler(filters.PHOTO | filters.VIDEO, process_album), group=1)
    
    log_message("🤖 Pixel-Perfect Bot started successfully!")
    application.run_polling()
