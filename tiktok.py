import os
import logging
import yt_dlp
import uuid
import time
import subprocess
from telegram import InputFile
from telegram.ext import ContextTypes
from config import DOWNLOAD_DIR
from platforms.proxy_manager import retry_with_sequential_proxy # Importăm modulul proxy_manager

logger = logging.getLogger(__name__)

async def send_video_to_user(context: ContextTypes.DEFAULT_TYPE, chat_id: int, video_file: str) -> None:
    try:
        if video_file and os.path.exists(video_file):
            logger.info(f'Trimiterea videoclipului către utilizator... File: {video_file}')

            ffprobe_command = [
                'ffprobe',
                '-v', 'error',
                '-select_streams', 'v:0',
                '-show_entries', 'stream=width,height',
                '-of', 'csv=s=x:p=0',
                video_file
            ]
            
            result = subprocess.run(ffprobe_command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            resolution = result.stdout.strip()
            
            if resolution:
                width, height = map(int, resolution.split('x'))
                logger.info(f'Resolution detected: {width}x{height}')
                
                with open(video_file, 'rb') as vf:
                    await context.bot.send_video(
                        chat_id=chat_id,
                        video=InputFile(vf),
                        width=width,
                        height=height
                    )
                logger.info('Videoclip trimis cu succes.')
            else:
                logger.error('Nu s-a putut detecta rezoluția. Videoclipul nu va fi trimis.')
                await context.bot.send_message(chat_id=chat_id, text='Eroare: Nu am putut detecta rezoluția videoclipului. Videoclipul nu va fi trimis.')
        else:
            logger.error(f'Videoclipul nu a fost găsit: {video_file}')
            await context.bot.send_message(chat_id=chat_id, text='Fișierul video nu a fost găsit.')
    except TimedOut:
        logger.error('Eroare la trimiterea videoclipului: Timed out')
        await context.bot.send_message(chat_id=chat_id, text='Eroare la trimiterea videoclipului: Timed out')
    except Exception as e:
        logger.error(f'Eroare la trimiterea videoclipului: {e}')
        await context.bot.send_message(chat_id=chat_id, text=f'Eroare la trimiterea videoclipului: {e}')
    finally:
        if os.path.exists(video_file):
            os.remove(video_file)

def check_and_fix_faststart(input_file):
    # Verifică dacă fișierul are flag-ul +faststart
    ffmpeg_check_command = [
        'ffmpeg',
        '-v', 'trace',
        '-i', input_file,
        '-c', 'copy',
        '-f', 'null', '-'
    ]

    try:
        result = subprocess.run(ffmpeg_check_command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        stderr_output = result.stderr

        moov_pos = stderr_output.find("type:'moov'")
        mdat_pos = stderr_output.find("type:'mdat'")

        if moov_pos != -1 and (mdat_pos == -1 or moov_pos < mdat_pos):
            logger.info(f"Fișierul {input_file} are deja flag-ul +faststart.")
            return input_file
        else:
            logger.info(f"Fișierul {input_file} nu are flag-ul +faststart. Aplicare flag...")
    except subprocess.CalledProcessError as e:
        logger.error(f"Eroare la verificarea flag-ului +faststart pentru {input_file}: {e}")
        return None
    except Exception as e:
        logger.error(f"Eroare la citirea ieșirii ffmpeg: {e}")
        return None

    output_file = input_file.replace(".mp4", "_faststart.mp4")
    ffmpeg_command = [
        'ffmpeg',
        '-y',
        '-i', input_file,
        '-c', 'copy',
        '-preset', 'superfast',
        '-movflags', '+faststart',
        output_file
    ]

    try:
        subprocess.run(ffmpeg_command, stderr=subprocess.PIPE, text=True)
        os.remove(input_file)
        logger.info(f"Flag-ul +faststart a fost adăugat pentru {output_file}")
        return output_file
    except subprocess.CalledProcessError as e:
        logger.error(f"Eroare la adăugarea flag-ului +faststart pentru {input_file}: {e}")
        return None

async def process_tiktok_video(url, context, chat_id):
    unique_id = str(uuid.uuid4())
    output_file = os.path.join(DOWNLOAD_DIR, f"tiktok_video_{unique_id}.mp4")

    try:
        download_start_time = time.time()

        # Funcția care va fi apelată cu rotația proxy-urilor
        def download_video_with_proxy(proxy):
            ydl_opts = {
                'format': 'bestvideo+bestaudio/best',
                'outtmpl': output_file,
                'proxy': proxy,
                'retries': 2,
            }
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([url])

        # Reîncercăm descărcarea folosind rotația proxy-urilor
        retry_with_sequential_proxy(download_video_with_proxy)

    except yt_dlp.utils.DownloadError as e:
        logger.error(f"Eroare la descărcare: {e}")
        await context.bot.send_message(chat_id=chat_id, text=f"Eroare la descărcarea videoclipului: {e}")
        return False

    final_file = check_and_fix_faststart(output_file)

    if final_file:
        await send_video_to_user(context, chat_id, final_file)
        return True
    else:
        logger.error("Eroare în timpul procesării +faststart.")
        await context.bot.send_message(chat_id=chat_id, text="Eroare în timpul procesării videoclipului.")
        return False

    final_end_time = time.time()
    total_duration = final_end_time - download_start_time
    logger.info(f"Timpul total pentru procesare: {total_duration:.2f} secunde")
