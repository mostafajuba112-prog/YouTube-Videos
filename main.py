import os
import json
import time
import shutil
import wave
import asyncio
import random
import urllib.parse
import requests
from PIL import Image, ImageFile
from io import BytesIO
from google import genai
from google.genai import types
import edge_tts
from moviepy.editor import (
    ImageClip, AudioFileClip, CompositeVideoClip, concatenate_videoclips,
)
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

ImageFile.LOAD_TRUNCATED_IMAGES = True

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
YOUTUBE_CLIENT_ID = os.environ.get("YOUTUBE_CLIENT_ID")
YOUTUBE_CLIENT_SECRET = os.environ.get("YOUTUBE_CLIENT_SECRET")
YOUTUBE_REFRESH_TOKEN = os.environ.get("YOUTUBE_REFRESH_TOKEN")

# public: الفيديو ينزل عام مباشرة. للتجربة غيّره إلى private
PRIVACY_STATUS = os.environ.get("PRIVACY_STATUS", "public")

VIDEO_SIZE = (1280, 720)

client = genai.Client(api_key=GEMINI_API_KEY)


def generate_story_script():
    print("Firing Gemini for completely free & diverse documentary topic selection...")

    prompt = """
    أنت كاتب سيناريو وثائقي عبقري ومبدع بلا حدود لقناة يوتيوب كبرى.
    المطلوب منك اختيار وتأليف قصة وثائقية طويلة ومشوقة جداً في "أي مجال وموضوع في الكون" (تاريخي، علمي، فلكي، غموض، جريمة، أساطير كبرى، صراعات عظمى، كوارث، استخبارات، خيال علمي واقعي، اختراعات غيرت التاريخ، أو أي موضوع مذهل يخطر على بالك ولا تقيد نفسك بقالب واحد).

    الشروط الصارمة للسكريبت:
    1. الإبداع الحر: اختر موضوعاً فريداً ومبهراً لم يستهلك كثيراً، واجعل الهيكل السردي يبدأ بمقدمة خاطفة للأنفاس تثير الفضول الفوري، ثم تصاعد درامي مذهل، وخاتمة حاسمة ومكتملة تماماً.
    2. اللغة والأسلوب: عربية فصحى سردية بسيطة، قوية، عميقة، ومناسبة للإلقاء الصوتي الوثائقي. بدون إيموجي أو عناوين جانبية داخل نصوص السرد.
    3. الطول والتقسيم: 25 مشهداً متسلسلاً باحتراف، كل مشهد فقرة سردية غنية ومفصلة (40 إلى 60 كلمة).
    4. لكل مشهد اكتب image_prompt بالإنجليزية دقيق يصف المشهد بصرياً بأسلوب سينمائي وثائقي واقعي وداكن (Cinematic documentary style, dramatic lighting, highly detailed, realistic) ويطابق تماماً ما يُقال في سرد المشهد.
    5. في حقل description، اكتب وصفاً احترافياً وموسعاً للقصة، وفي آخره ائتِ بـ 50 هاشتاج دقيق، متنوع، ومترابط تماماً مع موضوع الفيديو والقصة (مفصولة بمسافات).

    أخرج النتيجة بصيغة JSON حصراً بهذا الشكل ودون أي كود إضافي خارجه:
    {{
        "title": "عنوان فيديو يوتيوب وثائقي جذاب ومثير باللغة العربية",
        "description": "وصف احترافي وموسع للفيديو باللغة العربية يليه 50 هاشتاج دقيق ومتنوع له علاقة مباشرة بالموضوع",
        "tags": ["وثائقي", "قصص", "تاريخ", "غموض", "إثارة", "أسرار", "علوم", "كون"],
        "scenes": [
            {{
                "narration": "النص العربي الدقيق الذي سيقرأه المعلق في هذا المشهد",
                "image_prompt": "Detailed English visual prompt matching the narration"
            }}
        ]
    }}
    """

    for attempt in range(3):
        try:
            response = client.models.generate_content(
                model='gemini-2.5-flash',
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    temperature=1.0,  # درجة حرارة عالية لضمان أقصى إبداع وتنوع في الأفكار
                ),
            )
            data = json.loads(response.text)
            if "scenes" in data and len(data["scenes"]) >= 15:
                return data
        except Exception as e:
            print(f"Attempt {attempt + 1} failed for script generation: {e}")
            time.sleep(5)
    raise Exception("Failed to generate a valid long script after 3 attempts.")


async def _edge_save(text, output_path):
    voice = "ar-EG-ShakirNeural"  # صوت مصري طبيعي وممتاز
    communicate = edge_tts.Communicate(text, voice, rate="-8%")
    await communicate.save(output_path)


def generate_edge_audio(text, output_path):
    for attempt in range(3):
        try:
            asyncio.run(_edge_save(text, output_path))
            if os.path.exists(output_path) and os.path.getsize(output_path) > 0:
                return True
        except Exception as e:
            print(f"  Edge TTS retry {attempt + 1}/3 failed: {e}")
        time.sleep(3)
    return False


def generate_all_audio(scenes):
    files = []
    for idx, scene in enumerate(scenes):
        path = f"temp_assets/audio_{idx}.mp3"
        if not generate_edge_audio(scene["narration"], path):
            raise Exception(f"Edge TTS failed on scene {idx + 1}")
        files.append(path)
    return files


def download_image_with_retry(prompt, output_path, max_retries=4):
    encoded_prompt = urllib.parse.quote(prompt)

    for attempt in range(max_retries):
        seed = random.randint(1, 999999)
        url = (
            f"https://image.pollinations.ai/prompt/{encoded_prompt}"
            f"?width=1280&height=720&seed={seed}&nologo=true&model=flux"
        )
        try:
            response = requests.get(url, timeout=90)
            ctype = response.headers.get("content-type", "")
            print(f"  try {attempt + 1}: {response.status_code} {ctype}")
            if response.status_code == 200 and ctype.startswith("image"):
                img = Image.open(BytesIO(response.content)).convert("RGB")
                img = img.resize(VIDEO_SIZE, Image.Resampling.LANCZOS)
                img.save(output_path, "JPEG", quality=90)
                return True
        except Exception as e:
            print(f"  image retry {attempt + 1}/{max_retries} failed: {e}")
        time.sleep(10 * (attempt + 1))

    return False


def create_video_clips(scenes):
    os.makedirs("temp_assets", exist_ok=True)
    clips = []
    last_good_image = None
    failed_images = 0

    audio_files = generate_all_audio(scenes)

    for idx, scene in enumerate(scenes):
        print(f"Processing scene {idx + 1}/{len(scenes)}...")
        audio_file = audio_files[idx]
        image_file = f"temp_assets/image_{idx}.jpg"

        # 1. الصوت
        audio_clip = AudioFileClip(audio_file)
        duration = audio_clip.duration + 0.3

        # 2. الصورة (ولو فشلت نكرر آخر صورة نجحت بدل الشاشة السودا)
        ok = download_image_with_retry(scene["image_prompt"], image_file)
        if ok:
            last_good_image = image_file
        else:
            failed_images += 1
            print(f"  scene {idx + 1}: image failed")
            if last_good_image:
                shutil.copy(last_good_image, image_file)
            else:
                Image.new("RGB", VIDEO_SIZE, (15, 15, 20)).save(image_file, "JPEG")

        # 3. زوم خفيف داخل إطار ثابت 1280x720
        base = ImageClip(image_file).set_duration(duration)
        zoom = base.resize(lambda t: 1 + 0.03 * (t / duration)).set_position(("center", "center"))
        scene_clip = CompositeVideoClip([zoom], size=VIDEO_SIZE).set_duration(duration)
        scene_clip = scene_clip.set_audio(audio_clip)
        clips.append(scene_clip)

        time.sleep(6)  # راحة بين طلبات الصور عشان ما ناخدش rate limit

    print(f"Images failed: {failed_images}/{len(scenes)}")
    if failed_images > len(scenes) * 0.3:
        raise Exception("Too many images failed. Aborting so a bad video is not uploaded.")

    print("Concatenating final video...")
    final_video = concatenate_videoclips(clips, method="compose")
    output_filename = "final_long_video.mp4"
    final_video.write_videofile(
        output_filename,
        fps=24,
        codec="libx264",
        audio_codec="aac",
        threads=4,
        preset="ultrafast",
        ffmpeg_params=["-pix_fmt", "yuv420p"],
    )
    return output_filename


def upload_to_youtube(video_path, title, description, tags):
    print("Authenticating with YouTube...")
    creds = Credentials(
        token=None,
        refresh_token=YOUTUBE_REFRESH_TOKEN,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=YOUTUBE_CLIENT_ID,
        client_secret=YOUTUBE_CLIENT_SECRET,
    )
    creds.refresh(Request())
    youtube = build("youtube", "v3", credentials=creds)

    body = {
        "snippet": {
            "title": title[:95],
            "description": description,
            "tags": tags,
            "categoryId": "24",
        },
        "status": {
            "privacyStatus": PRIVACY_STATUS,
            "selfDeclaredMadeForKids": False,
        },
    }

    media = MediaFileUpload(video_path, chunksize=1024 * 1024 * 5, resumable=True)
    request = youtube.videos().insert(part="snippet,status", body=body, media_body=media)

    print(f"Uploading video to YouTube ({PRIVACY_STATUS})...")
    response = None
    while response is None:
        status, response = request.next_chunk()
        if status:
            print(f"Uploaded {int(status.progress() * 100)}%")

    print(f"Upload Complete! Video ID: {response.get('id')}")


if __name__ == "__main__":
    script_data = generate_story_script()
    print(f"Generated Title: {script_data['title']}")
    video_file = create_video_clips(script_data["scenes"])
    upload_to_youtube(
        video_file,
        script_data["title"],
        script_data["description"],
        script_data.get("tags", ["وثائقي", "قصص", "تاريخ"]),
    )
