#!/usr/bin/env python3
import os
import re
import sys
from datetime import datetime, timedelta

import pytz
import yt_dlp
import requests
from lxml import etree
from bs4 import BeautifulSoup

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


def extract_m3u8_from_page(url: str):
    """
    Metode alternatif: Ekstrak link M3U8 langsung dari halaman YouTube menggunakan requests dan BeautifulSoup
    :param url: URL YouTube
    :return: Link M3U8 atau None jika tidak ditemukan
    """
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, seperti Gecko) Chrome/120.0.0.0 Safari/537.36'
        }
        response = requests.get(url, headers=headers, timeout=15)
        if response.status_code != 200:
            return None
        
        # Cari link manifest.googlevideo.com dalam halaman
        content = response.text
        # Pola untuk mencari link HLS manifest
        patterns = [
            r'https://manifest\.googlevideo\.com/api/manifest/hls_variant/[^"\'\s<>]+\.m3u8',
            r'https://[a-z0-9\-]+\.googlevideo\.com/videoplayback[^"\'\s<>]+\.m3u8',
        ]
        
        for pattern in patterns:
            matches = re.findall(pattern, content)
            if matches:
                # Ambil link pertama yang ditemukan
                return matches[0]
        
        # Jika tidak ditemukan, coba cari di dalam script JSON
        json_pattern = r'"hlsManifestUrl":"([^"]+\.m3u8)"'
        json_matches = re.findall(json_pattern, content)
        if json_matches:
            # Escape karakter Unicode
            return json_matches[0].replace('\\u0026', '&')
        
        return None
    except Exception as e:
        print(f"DEBUG: Error in extract_m3u8_from_page: {e}", file=sys.stderr)
        return None


def grab_with_ytdlp(url: str):
    """
    Grab live-streaming URL using yt-dlp with multiple fallback methods
    :param url: The YouTube URL of the livestream
    """
    stream_url = None
    stream_title = 'Live Stream'
    stream_desc = 'No description'
    stream_image_url = ''
    
    # Method 1: Gunakan yt-dlp
    try:
        ydl_opts = {
            'quiet': True,
            'no_warnings': True,
            'extract_flat': False,
            'format': 'bestvideo+bestaudio/best',
            'ignoreerrors': True,
            'headers': {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, seperti Gecko) Chrome/120.0.0.0 Safari/537.36'
            }
        }
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            
            if info:
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
    except Exception as e:
        print(f"DEBUG: yt-dlp error: {e}", file=sys.stderr)
    
    # Method 2: Jika yt-dlp gagal, coba ekstrak dari halaman langsung
    if not stream_url or '.m3u8' not in stream_url:
        print(f"DEBUG: Trying fallback method for {url}", file=sys.stderr)
        fallback_url = extract_m3u8_from_page(url)
        if fallback_url:
            stream_url = fallback_url
            # Coba ambil judul dari halaman
            try:
                headers = {
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
                }
                resp = requests.get(url, headers=headers, timeout=10)
                if resp.status_code == 200:
                    soup = BeautifulSoup(resp.text, 'html.parser')
                    title_tag = soup.find('meta', property='og:title')
                    if title_tag:
                        stream_title = title_tag.get('content', 'Live Stream')
            except:
                pass
    
    # Method 3: Fallback terakhir - berikan link YouTube asli
    if not stream_url:
        print(f"DEBUG: All methods failed, using YouTube URL as fallback", file=sys.stderr)
        stream_url = url
        # Ambil informasi dari halaman untuk data EPG
        try:
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            }
            resp = requests.get(url, headers=headers, timeout=10)
            if resp.status_code == 200:
                soup = BeautifulSoup(resp.text, 'html.parser')
                title_tag = soup.find('meta', property='og:title')
                if title_tag:
                    stream_title = title_tag.get('content', 'Live Stream')
                desc_tag = soup.find('meta', property='og:description')
                if desc_tag:
                    stream_desc = desc_tag.get('content', 'No description')
                image_tag = soup.find('meta', property='og:image')
                if image_tag:
                    stream_image_url = image_tag.get('content', '')
        except:
            pass
    
    # Simpan data channel
    channels.append((channel_name, channel_id, category, stream_title, stream_desc, stream_image_url))
    
    # Cetak URL stream (ini yang akan masuk ke youtube.m3u8)
    print(stream_url)


# Variabel global
channel_name = ''
channel_id = ''
category = ''

# Baca file youtubeLink.txt
with open('./youtubeLink.txt', encoding='utf-8') as f:
    print("#EXTM3U")
    for line in f:
        line = line.strip()
        if not line or line.startswith('##'):
            continue
        if not line.startswith('https:'):
            parts = line.split('||')
            if len(parts) >= 3:
                channel_name = parts[0].strip()
                channel_id = parts[1].strip()
                category = parts[2].strip().title()
                print(
                    f'\n#EXTINF:-1 tvg-id="{channel_id}" tvg-name="{channel_name}" group-title="{category}", {channel_name}')
        else:
            grab_with_ytdlp(line)

# Build XMLTV
if channels:
    channel_xml = build_xml_tv(channels)
    with open('epg.xml', 'wb') as f:
        f.write(channel_xml)

# Cleanup
if 'temp.txt' in os.listdir():
    os.remove('temp.txt')
    for f in os.listdir():
        if f.startswith('watch'):
            os.remove(f)
