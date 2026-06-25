import os
import cv2
import numpy as np
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
        f"👋 **Hello {user.first_name}!**\n\n"
        f"🤖 **Studio Brand Bot**\n"
        f"I erase the bottom-right watermark completely, and place your brand in the center.\n\n"
        f"📌 **How to use:**\n"
        f"1️⃣ Set brand: `/setbrand YourBrandName`\n"
        f"2️⃣ Upload a photo or video.\n"
        f"3️⃣ Get a studio-clean result!\n\n"
        f"{brand_status}\n\n"
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
    await update.message.reply_text(f"✅ **Brand saved!**\n\n`{text}`\n\nUpload your media now.", parse_mode='Markdown')

async def handle_media(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in user_brands:
        await update.message.reply_text("⚠️ **Set your brand first!**\nUse `/setbrand YourBrandName`", parse_mode='Markdown')
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
        status_msg = await message.reply_text(f"⏳ **Processing {media_type}...**\n🧹 Erasing bottom-right watermark...", parse_mode='Markdown')
        await file.download_to_drive(input_path)
        
        if media_type == "photo":
            studio_erase_and_center(input_path, output_path, brand_text)
            await status_msg.delete()
            await message.reply_photo(photo=open(output_path, 'rb'))
        else:
            studio_video_erase_and_center(input_path, output_path, brand_text)
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
                studio_erase_and_center(input_path, output_path, brand_text)
                output_media.append({'type': 'photo', 'media': open(output_path, 'rb')})
            else:
                studio_video_erase_and_center(input_path, output_path, brand_text)
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
# 🎨 STUDIO-GRADE TEXT REMOVAL
# ==========================================

def studio_erase_and_center(input_path, output_path, new_text):
    """
    Removes the ENTIRE bottom-right corner using AI Inpainting.
    Then places the brand text perfectly in the CENTER of the screen.
    """
    img = cv2.imread(input_path)
    h, w, _ = img.shape

    # 1. Target the entire bottom-right 15% of the image
    crop_y = int(h * 0.85)  # Start 85% down
    crop_x = int(w * 0.80)  # Start 80% right
    box_h = h - crop_y
    box_w = w - crop_x

    # 2. Create a mask to tell OpenCV to erase this exact region
    mask = np.zeros((h, w), dtype=np.uint8)
    mask[crop_y:h, crop_x:w] = 255  # White = area to erase

    # 3. AI Inpainting (Generates seamless background)
    # Note: Requires opencv-contrib-python for full effect, but standard TELEA works great
    cleaned_img = cv2.inpaint(img, mask, 5, cv2.INPAINT_TELEA)

    # 4. Convert to PIL to add text
    pil_img = Image.fromarray(cv2.cvtColor(cleaned_img, cv2.COLOR_BGR2RGB))
    draw = ImageDraw.Draw(pil_img)
    
    # Calculate font size relative to image (Medium sized for center)
    font_size = int(min(h, w) * 0.05) 
    try:
        font = ImageFont.truetype("arial.ttf", font_size)
    except:
        font = ImageFont.load_default()
        
    bbox = draw.textbbox((0, 0), new_text, font=font)
    text_w = bbox[2] - bbox[0]
    text_h = bbox[3] - bbox[1]

    # 5. Place Text EXACTLY in the Middle (Copyright Style)
    center_x = (w - text_w) // 2
    center_y = (h - text_h) // 2

    # Draw a neat, semi-transparent black box behind the text for readabiity
    padding = 15
    draw.rectangle([center_x-padding, center_y-padding, center_x+text_w+padding, center_y+text_h+padding], fill=(0,0,0,160))
    # Draw the text in solid white
    draw.text((center_x, center_y), new_text, font=font, fill="white")
    
    pil_img.save(output_path)

def studio_video_erase_and_center(input_path, output_path, new_text):
    """
    Uses FFmpeg to paint a black box over the bottom-right corner,
    effectively removing the old watermark, then places text in the center.
    """
    safe_text = new_text.replace("'", r"\'").replace(":", r"\:")
    
    # Define the bottom-right corner region to paint black (15% width, 15% height)
    w_perc = 0.20  # 20% width from the right
    h_perc = 0.15  # 15% height from the bottom
    x_perc = 0.80  # Start 80% from left
    y_perc = 0.85  # Start 85% from top
    
    # Draw box to erase old watermark, then draw text in the center
    filter_complex = (
        f"[0:v]drawbox=w={w_perc}*iw:h={h_perc}*ih:x={x_perc}*iw:y={y_perc}*ih:color=black:t=fill[erased];"
        f"[erased]drawtext=text='{safe_text}':"
        f"fontcolor=white:fontsize=40:"
        f"box=1:boxcolor=black@0.5:boxborderw=10:"
        f"x=(w-text_w)/2:y=(h-text_h)/2[out]"  # EXACT CENTER FORMULA
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
    <title>🤖 Studio Brand Bot</title>
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
            <h1>🤖 Studio Brand Bot</h1>
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
    
    log_message("🤖 Studio Bot started successfully!")
    application.run_polling()
