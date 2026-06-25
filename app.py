import os
import cv2
import numpy as np
import pytesseract
import subprocess
from PIL import Image, ImageDraw, ImageFont
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# ==========================================
# DYNAMIC TESSERACT PATH (Works on Render & Windows)
# ==========================================
if os.name == 'nt':  # Windows
    pytesseract.pytesseract.tesseract_cmd = r'C:\Tesseract-OCR\tesseract.exe'
else:  # Linux (Render)
    # Render usually has tesseract in /usr/bin/
    pytesseract.pytesseract.tesseract_cmd = '/usr/bin/tesseract'

# Store user brands
user_brands = {}

# ==========================================
# BOT COMMANDS
# ==========================================
async def set_brand(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = ' '.join(context.args)
    if not text:
        await update.message.reply_text("Usage: /setbrand t.me/yourchannel")
        return
    user_brands[user_id] = text
    await update.message.reply_text(f"✅ Brand saved: {text}")

async def handle_media(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in user_brands:
        await update.message.reply_text("Please set your brand first with /setbrand t.me/...")
        return

    brand_text = user_brands[user_id]
    message = update.message

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
        await message.reply_text(f"🔍 Processing {media_type}... (Smart text removal)")
        await file.download_to_drive(input_path)
        
        if media_type == "photo":
            smart_remove_and_replace_image(input_path, output_path, brand_text)
            await message.reply_photo(photo=open(output_path, 'rb'))
        else:
            smart_remove_and_replace_video(input_path, output_path, brand_text)
            await message.reply_video(video=open(output_path, 'rb'))
            
    except Exception as e:
        await message.reply_text(f"❌ Error: {e}")
    finally:
        for path in [input_path, output_path]:
            if os.path.exists(path): os.remove(path)

async def process_album(update: Update, context: ContextTypes.DEFAULT_TYPE):
    album_id = update.message.media_group_id
    
    if 'albums' not in context.bot_data:
        return
        
    album_data = context.bot_data['albums'].pop(album_id, None)
    if not album_data:
        return

    user_id = album_data['user_id']
    brand_text = album_data['brand']
    messages = album_data['files']
    
    await update.message.reply_text(f"📦 Album detected! Processing {len(messages)} files... Please wait.")

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
                smart_remove_and_replace_image(input_path, output_path, brand_text)
                output_media.append({'type': 'photo', 'media': open(output_path, 'rb')})
            else:
                smart_remove_and_replace_video(input_path, output_path, brand_text)
                output_media.append({'type': 'video', 'media': open(output_path, 'rb')})
                
        except Exception as e:
            await update.message.reply_text(f"❌ Error on file {idx+1}: {e}")
        finally:
            if os.path.exists(input_path): os.remove(input_path)

    if output_media:
        await update.message.reply_media_group(media=output_media)
        for item in output_media:
            if os.path.exists(item['media'].name):
                os.remove(item['media'].name)

# ==========================================
# TEXT DETECTION & REPLACEMENT
# ==========================================
def smart_remove_and_replace_image(input_path, output_path, new_text):
    img = cv2.imread(input_path)
    h, w, _ = img.shape
    
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    _, thresh = cv2.threshold(gray, 150, 255, cv2.THRESH_BINARY_INV)
    data = pytesseract.image_to_data(thresh, output_type=pytesseract.Output.DICT)
    
    mask = np.zeros((h, w), dtype=np.uint8)
    text_found = False
    detected_text_coords = None

    for i in range(len(data['text'])):
        if int(data['conf'][i]) > 30:
            text = data['text'][i].strip()
            if text:
                x, y, w_box, h_box = data['left'][i], data['top'][i], data['width'][i], data['height'][i]
                padding = 15
                x = max(0, x - padding)
                y = max(0, y - padding)
                w_box = min(w - x, w_box + padding*2)
                h_box = min(h - y, h_box + padding*2)
                
                mask[y:y+h_box, x:x+w_box] = 255
                detected_text_coords = (x, y, w_box, h_box)
                text_found = True

    if not text_found:
        x = w - 400
        y = h - 100
        detected_text_coords = (x, y, 400, 100)
        mask[y:y+100, x:x+400] = 255

    cleaned_img = cv2.inpaint(img, mask, 3, cv2.INPAINT_TELEA)
    pil_img = Image.fromarray(cv2.cvtColor(cleaned_img, cv2.COLOR_BGR2RGB))
    draw = ImageDraw.Draw(pil_img)
    
    try:
        font = ImageFont.truetype("arial.ttf", 35)
    except:
        font = ImageFont.load_default()
        
    bbox = draw.textbbox((0, 0), new_text, font=font)
    text_w = bbox[2] - bbox[0]
    text_h = bbox[3] - bbox[1]

    x, y, old_w, old_h = detected_text_coords
    center_x = x + (old_w // 2) - (text_w // 2)
    center_y = y + (old_h // 2) - (text_h // 2)

    draw.rectangle([center_x-10, center_y-10, center_x+text_w+10, center_y+text_h+10], fill=(0,0,0,180))
    draw.text((center_x, center_y), new_text, font=font, fill="white")
    pil_img.save(output_path)

def smart_remove_and_replace_video(input_path, output_path, new_text):
    cap = cv2.VideoCapture(input_path)
    ret, first_frame = cap.read()
    cap.release()
    
    if not ret:
        raise Exception("Could not read video")
        
    h, w, _ = first_frame.shape
    gray = cv2.cvtColor(first_frame, cv2.COLOR_BGR2GRAY)
    _, thresh = cv2.threshold(gray, 150, 255, cv2.THRESH_BINARY_INV)
    data = pytesseract.image_to_data(thresh, output_type=pytesseract.Output.DICT)
    
    coords = None
    for i in range(len(data['text'])):
        if int(data['conf'][i]) > 30:
            text = data['text'][i].strip()
            if text:
                x, y, w_box, h_box = data['left'][i], data['top'][i], data['width'][i], data['height'][i]
                coords = (x, y, w_box, h_box)
                break
    
    if not coords:
        coords = (w-400, h-100, 400, 100)
    
    x, y, w_box, h_box = coords
    safe_text = new_text.replace("'", r"\'").replace(":", r"\:")
    
    x_perc = x / w
    y_perc = y / h
    w_perc = w_box / w
    h_perc = h_box / h
    
    filter_complex = (
        f"[0:v]split[orig][blur];"
        f"[blur]crop=iw*{w_perc}:ih*{h_perc}:iw*{x_perc}:ih*{y_perc},"
        f"gblur=sigma=15[blurred];"
        f"[orig][blurred]overlay=W*{x_perc}:H*{y_perc}[withblur];"
        f"[withblur]drawtext=text='{safe_text}':"
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
# MAIN
# ==========================================
if __name__ == "__main__":
   TOKEN = os.environ.get("BOT_TOKEN")
    
    application = Application.builder().token(TOKEN).build()
    application.add_handler(CommandHandler("setbrand", set_brand))
    application.add_handler(MessageHandler(filters.PHOTO | filters.VIDEO, handle_media))
    application.add_handler(MessageHandler(filters.PHOTO | filters.VIDEO, process_album), group=1)
    
    print("🤖 Bot Running...")
    application.run_polling()
