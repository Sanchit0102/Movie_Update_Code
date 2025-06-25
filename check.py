import re, base64, asyncio, aiohttp, io, math, random, string
from pyrogram import Client, filters, enums
from asyncio import create_task, sleep
from collections import defaultdict
from pyrogram.types import Message
from typing import Optional, List
from datetime import datetime
from bot import Bot

# === CONFIG ===
DB_CHANNEL = -1002325789513    # Replace with your DB channel ID
UPDATE_CHANNEL = -1002469127707 # Replace with your update channel ID
BOT_USERNAME = "Jarvis_moviebot"        # Without @

# Memory cache to group movie qualities
movie_cache = defaultdict(dict)
post_tasks = {}

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

    match = re.search(r"(.+?)\s*(19\d{2}|20\d{2})", test)
    if match:
        title = match.group(1).strip().title()
        title = re.sub(r"S\d{1,2}E\d{1,2}", "", title).strip()
        year = match.group(2)
    else:
        title_parts = re.split(r"(S\d{1,2}E\d{1,2}|Web[- ]?Rip|BluRay|HDRip|480p|720p|1080p)", text, flags=re.I)
        if title_parts:
            title = title_parts[0].strip().title()
        else:
            title = "N/A"
            year = ""
    print(f"Extracted Title: {title}, Year: {year}")
        
    if res := re.search(r"(2160p|1440p|1080p|720p|480p|360p|240p)", cap):
        resolution = res.group(1).upper()

    if "265" in cap or "hevc" in cap:
        codec = " HEVC"

    if q := re.search(r"(bluray|brrip|bdrip|hdts|hdtc|web[-\s]?dl|web[-\s]?rip|hdrip|dvdrip|hdtv|tvrip|uhd|camrip|hdcam|repack)", cap):
        quality = q.group(1).upper()

    langs = re.findall(r"(Hindi|Tamil|Marathi|Telugu|English|Malayalam|Kannada|Bengali|Punjabi|Dual Audio|Multi Audio)", text, re.I)
    if langs:
        audio = ", ".join(sorted(set([l.title() for l in langs])))

    ep_match = re.search(r"S\s?(\d{1,2})\s?E\s?(\d{1,2})", cap, re.I)
    episode_tag = f"S{ep_match.group(1).zfill(2)}E{ep_match.group(2).zfill(2)}" if ep_match else ""
        
    # Detect type by checking patterns
    is_episode = bool(re.search(r"S\d{1,2}E\d{1,2}", cap))
    is_combined = bool(re.search(r"S\d{1,2}E\d{1,2}-E\d{1,2}|complete|completed|batch|combined", cap))

    if is_combined:
        file_type = "series_combined"
    elif is_episode:
        file_type = "series_episode"
    else:
        file_type = "movie"
    
    if file_type == "movie":
        title_key = f"{title}_{year}"
    elif file_type == "series_combined":
        season = re.search(r"S(\d{1,2})", cap)
        title_key = f"{title}_S{season.group(1).zfill(2)}" if season else f"{title}_S01"
    else:  # series_episode
        season = re.search(r"S(\d{1,2})", cap)
        title_key = f"{title}_S{season.group(1).zfill(2)}" if season else f"{title}_S01"
   
    quality_key = episode_tag or f"{resolution}{codec}".strip()

    size_mb = size_bytes / (1024 * 1024)
    size = f"{size_mb:.1f}MB" if size_mb < 1024 else f"{size_mb / 1024:.1f}GB"
    
    print(f"File Type: {file_type}, Title Key: {title_key}, Quality Key: {quality_key}, Size: {size}")
    return title, year, quality, audio, size, title_key, quality_key, file_type, episode_tag

def build_movie_caption(title, year, quality, audio, file_dict):
    cap = f"<b><blockquote>✅ 𝖭𝖤𝖶 𝖥𝖨𝖫𝖤 𝖠𝖣𝖣𝖤𝖣</blockquote></b>\n\n"
    cap += f"🎬 <b>Title</b>     : {title} {year}\n"
    cap += f"📀 <b>Quality</b>   : {quality}\n"
    cap += f"🎧 <b>Audio</b>     : {audio}\n\n"
    cap += f"<b><blockquote>✨ Telegram Files ✨</blockquote></b>\n\n"
    for q, d in sorted(file_dict.items()):
        cap += f"📦 <b>{q}</b> : <a href='{d['link']}'>{d['size']} 🚀</a>\n\n"
    cap += "<b>𝖯𝗈𝗐𝖾𝗋𝖾𝖽 𝖡𝗒 Master ⚡️</b>"
    return cap

def build_series_caption(title, season, quality, file_dict, combined=False, batch_link=None):
    mode = "COMBINED" if combined else "EPISODEWISE"
    cap = f"<b><blockquote>🎞️ NEW SERIES FILES ADDED</blockquote></b>\n\n"
    cap += f"🎬 <b>Title</b>    : {title} {season}\n"
   # cap += f"📅 <b>Season</b>    : {season}\n"
    cap += f"📀 <b>Quality</b>   : {quality}\n"
    cap += f"📺 <b>Episodes</b>  : {len(file_dict)}\n"
    cap += f"🔗 <b>Type</b>      : {mode}\n\n"
    cap += f"<b><blockquote>✨ Telegram Files ✨</blockquote></b>\n\n"
    for ep, d in sorted(file_dict.items()):
        cap += f"📦 <b>{ep}</b> : <a href='{d['link']}'>{d['size']} 🚀</a>\n"
    cap += f"<b>𝖯𝗈𝗐𝖾𝗋𝖾𝖽 𝖡𝗒 Master ⚡️</b>"
    return cap, InlineKeyboardMarkup([[InlineKeyboardButton("📥 Get All Files", url=batch_link)]])
    
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
                    raise ValueError(f"No poster found for: {title}")
                elif response.status == 500:
                    raise ValueError(f"Server error: {response_text}")
                else:
                    raise ValueError(f"API error: HTTP {response.status} - {response_text}")
    except aiohttp.ClientError as e:
        print(f"Network error occurred: {str(e)}")
    except asyncio.TimeoutError:
        print("Request timed out after 20 seconds")
    except ValueError as e:
        print(str(e))
    except Exception as e:
        print(f"Unexpected error: {str(e)}")   
    return None 

async def generate_random_filename(extension=".jpg"):
    try:
        now = datetime.now()
        timestamp = now.strftime("%Y%m%d%H%M%S")
        sin_value = abs(math.sin(int(timestamp[-5:]))) 
        random_part = ''.join(random.choices(string.ascii_lowercase + string.digits, k=6))   
        filename = f"silentxbotz_{int(sin_value*10000)}_{random_part}{extension}"
        return filename
    except Exception as e:
        print(e)
        return

def get_file_link(bot_username, msg_id):
    link = f"https://t.me/{bot_username}?start=ghost-{encode_msg_id(msg_id)}"
    print(f"Generated file link: {link}")
    return link
    
def get_batch_link(bot_username, msg_ids):
    links = f"https://t.me/{bot_username}?start=batch-{encode_batch_id(msg_ids)}"
    print((f"Generated Batch link: {links}"))
    return links
    
async def delayed_post(title_key, client: Client):
    print(f"⏳ Waiting to group files for: {title_key}")
    await asyncio.sleep(5)
    files = movie_cache.get(title_key)
    if not files:
        print("⚠️ Cache expired before post.")
        return
    first = next(iter(files.values()))
    title = first['title']
    poster = await fetch_movie_poster(title)
    image = "https://te.legra.ph/file/88d845b4f8a024a71465d.jpg"
    
    if first['file_type'] == "movie":
        caption = build_movie_caption(title, first['year'], first['quality'], first['audio'], files)
        reply_markup = None
    else:
        batch_link = get_batch_link(BOT_USERNAME, [f['msg_id'] for f in files.values()])
        caption, reply_markup = build_series_caption(title, title_key.split("_")[-1], first['quality'], files, combined=(first['file_type'] == 'series_combined'), batch_link=batch_link)

    try:
        if poster:
            photo = io.BytesIO(poster)
            photo.name = await generate_random_filename()
            await client.send_photo(UPDATE_CHANNEL, photo, caption=caption, parse_mode=enums.ParseMode.HTML, reply_markup=reply_markup)
        else:
            await client.send_photo(UPDATE_CHANNEL, image, caption=caption, parse_mode=enums.ParseMode.HTML, reply_markup=reply_markup)
        await client.send_sticker(chat_id=UPDATE_CHANNEL, sticker="CAACAgUAAxkBAAKyA2hZF-I7Gkdkzaxdl-DQJZWduRu6AAI9AANDc8kSqGMX96bLjWE2BA")
        print("✅ Successfully posted to update channel!")
    except Exception as e:
        print(f"Error in posting file: {e}")
    finally:
        movie_cache.pop(title_key, None)
        post_tasks.pop(title_key, None)

@Bot.on_message(filters.chat(DB_CHANNEL) & (filters.document | filters.video))
async def movie_file_handler(client: Client, message: Message):
    try:
        media = message.document or message.video
        if not media:
            return
        print("Checking New Files In Database")
        file_name = media.file_name or ""
        file_size = media.file_size or 0
        caption = message.caption or ""

        title, year, quality, audio, size, title_key, quality_key, file_type, ep_tag = extract_info(caption, file_name, file_size)
        
        movie_cache[title_key][quality_key] = {
            "msg_id": message.id,
            "size": size,
            "link": get_file_link(BOT_USERNAME, message.id),
            "title": title,
            "year": year,
            "quality": quality,
            "audio": audio,
            "file_type": file_type,
            "ep": ep_tag
        }
        
        print(f"Cached file: {title_key} -> {quality_key}")
        if title_key in post_tasks:
            post_tasks[title_key].cancel()
        post_tasks[title_key] = create_task(delayed_post(title_key, client))
    except Exception as e:
        print(f"❌ Handler error: {e}")
    
