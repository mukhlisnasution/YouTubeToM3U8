#!/usr/bin/env python3
import os
from datetime import datetime, timedelta

import pytz
import yt_dlp
from lxml import etree

tz = pytz.timezone('Europe/London')
channels = []


def generate_times(curr_dt: datetime):
    """
    Generate 3-hourly blocks of times based on a current date
    :param curr_dt: The current time the script is executed
    :return: A tuple that contains a list of start dates and a list of end dates
    """
    # Floor the last hour (e.g. 13:54:00 -> 13:00:00) and add timezone information
    last_hour = curr_dt.replace(microsecond=0, second=0, minute=0)
    last_hour = tz.localize(last_hour)
    start_dates = [last_hour]

    # Generate start times that are spaced out by three hours
    for x in range(7):
        last_hour += timedelta(hours=3)
        start_dates.append(last_hour)

    # Copy everything except the first start date to a new list, then add a final end date three hours after the last
    # start date
    end_dates = start_dates[1:]
    end_dates.append(start_dates[-1] + timedelta(hours=3))

    return start_dates, end_dates


def build_xml_tv(streams: list) -> bytes:
    """
    Build an XMLTV file based on provided stream information
    :param streams: List of tuples containing channel/stream name, ID and category
    :return: XML as bytes
    """
    data = etree.Element("tv")
    data.set("generator-info-name", "youtube-live-epg")
    data.set("generator-info-url", "https://github.com/dp247/YouTubeToM3U8")

    for stream in streams:
        channel = etree.SubElement(data, "channel")
        channel.set("id", stream[1])
        name = etree.SubElement(channel, "display-name")
        name.set("lang", "en")
        name.text = stream[0]

        dt_format = '%Y%m%d%H%M%S %z'
        start_dates, end_dates = generate_times(datetime.now())

        for idx, val in enumerate(start_dates):
            programme = etree.SubElement(data, 'programme')
            programme.set("channel", stream[1])
            programme.set("start", val.strftime(dt_format))
            programme.set("stop", end_dates[idx].strftime(dt_format))

            title = etree.SubElement(programme, "title")
            title.set('lang', 'en')
            title.text = stream[3] if stream[3] != '' else f'LIVE: {stream[0]}'
            description = etree.SubElement(programme, "desc")
            description.set('lang', 'en')
            description.text = stream[4] if stream[4] != '' else 'No description provided'
            icon = etree.SubElement(programme, "icon")
            icon.set('src', stream[5])

    return etree.tostring(data, pretty_print=True, encoding='utf-8')


def grab_with_ytdlp(url: str):
    """
    Grabs the live-streaming URL using yt-dlp
    :param url: The YouTube URL of the livestream
    """
    ydl_opts = {
        'quiet': True,
        'no_warnings': True,
        'extract_flat': False,
        'format': 'bestvideo+bestaudio/best',
        'ignoreerrors': True,
    }
    
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            
            if info is None:
                raise Exception("No video information retrieved")
            
            stream_url = None
            stream_title = info.get('title', 'Live Stream')
            stream_desc = info.get('description', 'No description')
            stream_image_url = info.get('thumbnail', '')
            
            # Cari format HLS (m3u8) terlebih dahulu
            for fmt in info.get('formats', []):
                if fmt.get('protocol') == 'm3u8_native' or '.m3u8' in fmt.get('url', ''):
                    stream_url = fmt['url']
                    break
            
            # Jika tidak ada format m3u8, ambil URL video langsung
            if not stream_url:
                stream_url = info.get('url')
            
            if not stream_url:
                raise Exception("No stream URL found in any format")
            
            channels.append((channel_name, channel_id, category, stream_title, stream_desc, stream_image_url))
            print(stream_url)
            
    except Exception as e:
        # Log error untuk debugging (tidak muncul di output final)
        import sys
        print(f"ERROR: {e}", file=sys.stderr)
        # Fallback: cetak link YouTube asli agar pemutar bisa mengambil langsung
        print(url)


# Variabel global untuk menyimpan data channel saat ini
channel_name = ''
channel_id = ''
category = ''

# Baca file youtubeLink.txt dan proses setiap baris
with open('./youtubeLink.txt', encoding='utf-8') as f:
    print("#EXTM3U")
    for line in f:
        line = line.strip()
        if not line or line.startswith('##'):
            continue
        if not line.startswith('https:'):
            # Parse baris info channel: Nama || ID || Kategori
            parts = line.split('||')
            channel_name = parts[0].strip()
            channel_id = parts[1].strip()
            category = parts[2].strip().title()
            print(
                f'\n#EXTINF:-1 tvg-id="{channel_id}" tvg-name="{channel_name}" group-title="{category}", {channel_name}')
        else:
            # Proses link YouTube dengan yt-dlp
            grab_with_ytdlp(line)

# Bangun file XMLTV berdasarkan data channel yang berhasil diambil
channel_xml = build_xml_tv(channels)
with open('epg.xml', 'wb') as f:
    f.write(channel_xml)

# Bersihkan file temporary jika ada
if 'temp.txt' in os.listdir():
    os.remove('temp.txt')
    for f in os.listdir():
        if f.startswith('watch'):
            os.remove(f)
