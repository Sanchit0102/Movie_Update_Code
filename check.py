# ==========================================================[ start.py ]========================================================== #

import asyncio, random, string
from .movieupdate import decode_msg_id, decode_batch_id
from pyrogram import Client, filters, enums
from pyrogram.errors import FloodWait, UserIsBlocked, InputUserDeactivated
from config import DB_CHANNEL, FILE_DEL_TIME

def get_sec(time):
    return int(time * 60)
    
@Client.on_message(filters.command('start') & filters.private & subscribed & subscribed2)
async def start_command(client, message):
    id = message.from_user.id
    if len(message.command) > 1:
        payload = message.command[1]
        if payload.startswith("silent-"):
            encoded_id = payload.replace("silent-", "", 1)
            try:
                msg_id = decode_msg_id(encoded_id)
                msg = await client.get_messages(DB_CHANNEL, msg_id)
                cap = msg.caption.html if msg.caption else ""
                cap = f"<a href='https://t.me/THE_DS_OFFICIAL'>{cap}</a>"
                t = await msg.copy(
                    chat_id=id,
                    caption=cap,
                    parse_mode=enums.ParseMode.HTML 
                    )
                m = await message.reply(f"<b>⏳ This file will auto-delete in {FILE_DEL_TIME} mins.</b>")
                await asyncio.sleep(get_sec(FILE_DEL_TIME))
                await t.delete()
                await m.edit("✅ File auto-deleted Successfully.")
            except Exception as e:
                print("❌ Error decoding ghost link:", e)
                await message.reply("❌ Invalid or expired link.")
            return

        # For batch download
        if payload.startswith("ghost-"):
            encoded = payload.replace("ghost-", "", 1)
            try:
                id_list = decode_batch_id(encoded)
                temp_msg = await message.reply("⏳ Fetching all files...")
                sent_msgs = []
                for msg_id in id_list:
                    msg = await client.get_messages(DB_CHANNEL, msg_id)
                    cap = msg.caption.html if msg.caption else ""
                    cap = f"<a href='https://t.me/THE_DS_OFFICIAL'>{cap}</a>"
                    try:
                        snt = await msg.copy(
                            chat_id=id,
                            caption=cap,
                            parse_mode=enums.ParseMode.HTML
                        )
                        sent_msgs.append(snt)
                        await asyncio.sleep(0.5)
                    except FloodWait as e:
                        await asyncio.sleep(e.value)
                await temp_msg.delete()

                notice = await message.reply(f"<b>⏳ This file will auto-delete in {get_exp_time(SECONDS)}.</b>")
                await asyncio.sleep(get_sec(FILE_DEL_TIME))
                for m in sent_msgs:
                    try:
                        await m.delete()
                    except:
                        pass
                await notice.edit("<b>✅ Files auto-deleted.</b>")
        except Exception as e:
            print("❌ Batch Decode Error:", e)
            await message.reply("❌ Invalid batch link")
        return
            

# ==========================================================[ movieupdate.py ]========================================================== #

import re, base64, asyncio, aiohttp, io, math, random, string
from pyrogram import Client, filters, enums
from asyncio import create_task
from collections import defaultdict
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from typing import Optional, List
from datetime import datetime
from config import DB_CHANNEL, UPDATE_CHANNEL, BOT_USERNAME

# Memory cache to group movie qualities
movie_cache = defaultdict(list)
post_tasks = {}
RES_ORDER = ["2160P", "1440P", "1080P", "1080P HEVC", "720P", "720P HEVC", "540P", "480P", "480P HEVC", "360P", "240P"]

# === SINGLE FILE ENCODE / DECODE (for ghost-) ===
def encode_msg_id(msg_id: int) -> str:
    return base64.urlsafe_b64encode(str(msg_id).encode("ascii")).decode("ascii").rstrip("=")

def decode_msg_id(encoded: str) -> int:
    encoded += '=' * (-len(encoded) % 4)
    return int(base64.urlsafe_b64decode(encoded.encode("ascii")).decode("ascii"))

# === MULTI FILE ENCODE / DECODE (for batch-) ===
def encode_batch_id(msg_ids: List[int]) -> str:
    msg_str = ",".join(map(str, msg_ids))
    encoded = base64.urlsafe_b64encode(msg_str.encode("ascii")).decode("ascii").rstrip("=")
    return encoded

def decode_batch_id(encoded: str) -> List[int]:
    encoded += '=' * (-len(encoded) % 4)
    decoded = base64.urlsafe_b64decode(encoded.encode("ascii")).decode("ascii")
    return list(map(int, decoded.split(",")))

def clean_text(text):
    return re.sub(r'http\S+|@\w+|#\w+|[\[\](){}.:;\-_!@]', ' ', text).replace("'", '').replace("  ", " ").replace("Title", "").replace("Filename", "").replace("Name", "").replace("Caption", "").strip()

# Extract movie or series info
def extract_info(caption: str, filename: str, size_bytes: int):
    raw_text = f"{caption or ''} {filename or ''}"
    text = clean_text(raw_text)
    test = clean_text(caption or "") 
    cap = text.lower()

    title = ""
    year = ""
    quality = "WEB-DL"
    audio = "-"
    resolution = ""
    codec = ""
    episode_tag = ""

    # Step 1: Clean series-related tags before extracting title
    title_text = re.sub(r"S\d{1,2}\s?E\d{1,2}(-E\d{1,2})?", "", test, flags=re.I)
    title_text = re.sub(r"\b(Ep|Episode)\s?\d{1,2}(-\d{1,2})?", "", title_text, flags=re.I)
    title_text = re.sub(r"(Web[- ]?Rip|BluRay|HDRip|480p|720p|1080p|2160p|HEVC|x265|x264|H264|H265)", "", title_text, flags=re.I)

    match = re.search(r"(.+?)\s*(19\d{2}|20\d{2})", title_text)
    if match:
        title = match.group(1).strip().title().replace("combined", "").replace("complete", "")
        year = match.group(2)
    else:
        title_fallback = re.sub(r"S\d{1,2}\s?E\d{1,2}(-E\d{1,2})?", "", text, flags=re.I)
        title_fallback = re.sub(r"\b(Ep|Episode)\s?\d{1,2}(-\d{1,2})?", "", title_fallback, flags=re.I)
        title_fallback = re.split(r"(Web[- ]?Rip|BluRay|HDRip|480p|720p|1080p|2160p)", title_fallback, flags=re.I)[0]
        title = title_fallback.strip().title().replace("combined", "").replace("complete", "")
        year = ""
    
    print(f"Extracted Title: {title}, Year: {year}")
        
    if res := re.search(r"(2160p|1440p|1080p|720p|540p|480p|360p|240p)", cap):
        resolution = res.group(1).upper()

    if "265" in cap or "hevc" in cap:
        codec = " HEVC"

    if q := re.search(r"(bluray|brrip|bdrip|hdts|hdtc|web[-\s]?dl|web[-\s]?rip|hdrip|dvdrip|hdtv|tvrip|uhd|camrip|hdcam|repack)", cap):
        quality = q.group(1).upper()

    langs = re.findall(r"(Hindi|Tamil|Marathi|Telugu|English|Malayalam|Kannada|Bengali|Punjabi|Dual Audio|Multi Audio|Multi)", text, re.I)
    if langs:
        audio = ", ".join(sorted(set([l.title() for l in langs])))

    ep_match = re.search(r"S\s?(\d{1,2})\s?E\s?(\d{1,2})", cap, re.I) \
        or re.search(r"Episode\s?(\d{1,2})", cap, re.I) \
        or re.search(r"Ep\s?(\d{1,2})", cap, re.I) \
        or re.search(r"[Ss](\d{1,2})[\s._-]?[Ee](\d{1,2})", cap, re.I)

    if ep_match:
        if len(ep_match.groups()) == 2:
            episode_tag = f"S{ep_match.group(1).zfill(2)}E{ep_match.group(2).zfill(2)}"
        else:
            episode_tag = f"E{ep_match.group(1).zfill(2)}"
    
    is_combined = bool(re.search(r"S\d{1,2}\s?E\d{1,2}-?E\d{1,2}|complete|completed|batch|combined", cap, re.I))
    is_episode = bool(ep_match)#re.search(r"(S\d{1,2}\s?E\d{1,2})|(Episode\s?\d{1,2})|(Ep\s?\d{1,2})", cap, re.I))

    if is_combined:
        file_type = "series_combined"
    elif is_episode:
        file_type = "series_episode"
    else:
        file_type = "movie"

    
    season = re.search(r"S(\d{1,2})", cap, re.I)
    season_tag = f"{season.group(1).zfill(2)}" if season else ""
    
    title_key = f"{title}_{season_tag}" if file_type != "movie" else f"{title}_{year or ''}"

   # quality_key = episode_tag or f"{resolution}{codec}".strip()
    quality_key = f"{resolution}{' HEVC' if codec else ''}".strip()
    size_mb = size_bytes / (1024 * 1024)
    size = f"{size_mb:.1f}MB" if size_mb < 1024 else f"{size_mb / 1024:.1f}GB"
   
    print(f"File Type: {file_type}, Title Key: {title_key}, Quality Key: {quality_key}, Size: {size}")
    return title, year, quality, audio, size, title_key, quality_key, file_type, episode_tag

def build_movie_caption(title, year, quality, audio, files):
    cap = f"<b><blockquote>✅ 𝖭𝖤𝖶 𝖥𝖨𝖫𝖤 𝖠𝖣𝖣𝖤𝖣</blockquote></b>\n\n"
    cap += f"🎬 <b>Title</b>     : {title} {year}\n"
    cap += f"📀 <b>Quality</b>   : {quality}\n"
    cap += f"🎧 <b>Audio</b>     : {audio}\n\n"
    cap += f"<b><blockquote>✨ Telegram Files ✨</blockquote></b>\n\n"
    #for q, d in sorted(file_dict.items()):
        #cap += f"📦 <b>{q}</b> : <a href='{d['link']}'>{d['size']} 🚀</a>\n\n"
    #cap += "<b>𝖯𝗈𝗐𝖾𝗋𝖾𝖽 𝖡𝗒 Master ⚡️</b>"
    #return cap
    groups = defaultdict(list)
    for file in files:
        res = file['quality_key']
        groups[res].append(f"<a href='{file['link']}'>{file['size']}</a>")

    for res in RES_ORDER:
        key = res
        if res not in groups:
            continue
        cap += f"📦 <b>{res}</b> : {' | '.join(groups[res])} 🚀\n\n"
    cap += "<b>𝖯𝗈𝗐𝖾𝗋𝖾𝖽 𝖡𝗒 Master ⚡️</b>"
    return cap

def build_series_caption(title, season, quality, files, file_type, batch_link):
    cap = f"<b><blockquote>✅ 𝖭𝖤𝖶 SERIES 𝖠𝖣𝖣𝖤𝖣</blockquote></b>\n\n"
    cap += f"🎬 <b>Title</b>     : <code>{title}</code> S{season} #SERIES\n"
    cap += f"🍿 <b>Season</b>    : {season}\n"
    cap += f"📀 <b>Format</b>   : {quality}\n"
    cap += f"🎧 <b>Audio</b>     : {files[0]['audio']}\n\n"
    cap += f"<b><blockquote>✨ Telegram Files ✨</blockquote></b>\n\n"
    
    #for ep, d in sorted(file_dict.items()):
        #cap += f"📦 <b>{ep}</b> : <a href='{d['link']}'>{d['size']} 🚀</a>\n"
    #cap += f"<b>𝖯𝗈𝗐𝖾𝗋𝖾𝖽 𝖡𝗒 Master ⚡️</b>"
    #return cap, InlineKeyboardMarkup([[InlineKeyboardButton("📥 Get All Files", url=batch_link)]])
    
    if file_type == "series_combined":
        groups = defaultdict(list)
        for f in files:
            groups[f['quality_key']].append(f"<a href='{f['link']}'>{f['size']}</a>")
        for res in RES_ORDER:
            if res in groups:
                cap += f"📦 <b>{res} Combined</b> : {' | '.join(groups[res])} 🚀\n\n"
    else:
        cap += f"<a href='{batch_link}'>𝖢𝗅𝗂𝖼𝗄 𝖧𝖾𝗋𝖾 𝖳𝗈 𝖦𝖾𝗍 𝖠𝗅𝗅 𝖤𝗉𝗂𝗌𝗈𝖽𝖾𝗌 🗃️</a>\n\n"
        #eps = defaultdict(list)
        #for f in files:
            #eps[f['quality_key']].append(f)
        #for res in RES_ORDER:
            #if res in eps:
                #cap += f"📦 <b>{res}</b> : "
                #line = " | ".join([f"{f['ep']}: <a href='{f['link']}'>{f['size']}</a>" for f in eps[res]])
               # cap += line + " 🚀\n\n"
       # for res in RES_ORDER:
            #if res in eps:
                #cap += f"📦 <b>{res}</b> :\n\n"
                #parts = []
               # for f in eps[res]:
                   # ep_num = f['ep']
                  #  ep_tag = ep_num[-2:] if ep_num else "-"
                   # parts.append(f"E{ep_tag}: <a href='{f['link']}'>{f['size']}</a>")
                #cap += " | ".join(parts) + " 🚀\n\n""""
    cap += "<b>𝖯𝗈𝗐𝖾𝗋𝖾𝖽 𝖡𝗒 Master ⚡️</b>"
    markup = InlineKeyboardMarkup([[InlineKeyboardButton("📥 Get All Files 📥", url=batch_link)]])
    return cap, markup
    
# Fetch poster using external API
async def fetch_movie_poster(title: str, year: Optional[int] = None) -> Optional[str]:
    base_url = "https://image.silentxbotz.tech/api/v1/poster"
    params = {"title": title.strip()}    
    if year is not None:
        params["year"] = str(year)
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                base_url,
                params=params,
                timeout=aiohttp.ClientTimeout(total=20)
            ) as response:
                if response.status == 200:
                    image_data = await response.read()
                    return image_data                
                response_text = await response.text()
                if response.status == 400:
                    raise ValueError(f"Invalid request: {response_text}")
                elif response.status == 404:
                    print(f"No poster found for: {title}")
                elif response.status == 500:
                    print(f"Server error: {response_text}")
                else:
                    print(f"API error: HTTP {response.status} - {response_text}")
    except aiohttp.ClientError as e:
        print(f"Network error occurred: {str(e)}")
    except asyncio.TimeoutError:
        print("Request timed out after 20 seconds")
    except Exception as e:
        print(f"Unexpected error: {str(e)}")   
    return None 
    
async def delayed_post(title_key, client: Client):
    print(f"⏳ Waiting to group files for: {title_key}")
    await asyncio.sleep(5)
    #files = movie_cache.get(title_key)
    files = movie_cache.get(title_key, [])
    if not files:
        print("⚠️ Cache expired before post.")
        return
    
    first = files[0]
    title, year, quality, audio, file_type, season = first['title'], first['year'], first['quality'], first['audio'], first['file_type'], title_key.split("_")[-1]
    poster = await fetch_movie_poster(title)
    image = "https://te.legra.ph/file/88d845b4f8a024a71465d.jpg"
    batch_link = f"https://t.me/{BOT_USERNAME}?start=ghost-{encode_batch_id([f['msg_id'] for f in files])}"

    if file_type == "movie":
        cap = build_movie_caption(title, year, quality, audio, files)
        markup = None
    else:
        cap, markup = build_series_caption(title, season, quality, files, file_type, batch_link)
        
    try:
        if poster:
            photo = io.BytesIO(poster)
            photo.name = f"ghost_{random.randint(1,10000)}.jpg"
            await client.send_photo(UPDATE_CHANNEL, photo, caption=cap, parse_mode=enums.ParseMode.HTML, reply_markup=markup)
        else:
            await client.send_photo(UPDATE_CHANNEL, image, caption=cap, parse_mode=enums.ParseMode.HTML, reply_markup=markup)
        await client.send_sticker(chat_id=UPDATE_CHANNEL, sticker="CAACAgUAAxkBAAKyA2hZF-I7Gkdkzaxdl-DQJZWduRu6AAI9AANDc8kSqGMX96bLjWE2BA")
        print("✅ Successfully posted to update channel!")
    except Exception as e:
        print(f"Error in posting: {e}")
    finally:
        movie_cache.pop(title_key, None)
        post_tasks.pop(title_key, None)

@Client.on_message(filters.chat(DB_CHANNEL) & (filters.document | filters.video))
async def movie_file_handler(client, message):
    try:
        media = message.document or message.video
        if not media:
            return
        print("Checking New Files In Database")
        file_name = media.file_name or ""
        file_size = media.file_size or 0
        caption = message.caption or ""

        title, year, quality, audio, size, title_key, quality_key, file_type, ep_tag = extract_info(caption, file_name, file_size)
        link = f"https://t.me/{BOT_USERNAME}?start=silent-{encode_msg_id(message.id)"
        movie_cache[title_key].append({
            "msg_id": message.id,
            "size": size,
            "link": link,
            "title": title,
            "year": year,
            "quality": quality,
            "audio": audio,
            "file_type": file_type,
            "ep": ep_tag,
            "quality_key": quality_key
        })

        if title_key in post_tasks:
            post_tasks[title_key].cancel()
        post_tasks[title_key] = create_task(delayed_post(title_key, client))

    except Exception as e:
        print(f"Handler error: {e}")
