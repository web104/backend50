from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from typing import Optional
import httpx
import os
import logging
import hashlib
import json
import time
import re
from datetime import datetime, timedelta

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Social Media Downloader API", version="5.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

ADMIN_CONFIG_FILE = "admin_config.json"
DEFAULT_ADMIN = {
    "username": "admin",
    "password_hash": hashlib.sha256("admin".encode()).hexdigest(),
    "website_name": "Social Media Downloader",
    "tagline": "Download videos from YouTube, Instagram, TikTok & more",
    "logo_url": "",
    "adsense_code": "",
    "ads_txt": "",
    "monetization_enabled": False,
    "monetization_link": "",
    "monetization_clicks": 2,
    "cron_secret": "SECRET_KEY_CHANGE_ME"
}

def load_config():
    if os.path.exists(ADMIN_CONFIG_FILE):
        try:
            with open(ADMIN_CONFIG_FILE, 'r') as f:
                return json.load(f)
        except:
            return DEFAULT_ADMIN.copy()
    return DEFAULT_ADMIN.copy()

def save_config(config):
    with open(ADMIN_CONFIG_FILE, 'w') as f:
        json.dump(config, f, indent=2)

admin_config = load_config()
active_sessions = {}

class DownloadRequest(BaseModel):
    url: str
    format: str = "best"

class AdminLogin(BaseModel):
    username: str
    password: str

def extract_video_id(url: str) -> Optional[str]:
    """Extract YouTube video ID"""
    patterns = [
        r'(?:youtube\.com\/watch\?v=|youtu\.be\/)([^&\n?#]+)',
        r'youtube\.com\/embed\/([^&\n?#]+)',
    ]
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    return None

async def download_from_invidious(video_id: str) -> dict:
    """Download using Invidious API - working alternative"""
    invidious_instances = [
        "https://invidious.jing.rocks",
        "https://inv.tux.pizza",
        "https://invidious.privacyredirect.com",
        "https://vid.puffyan.us"
    ]
    
    for instance in invidious_instances:
        try:
            api_url = f"{instance}/api/v1/videos/{video_id}"
            
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.get(api_url)
                
                if response.status_code == 200:
                    data = response.json()
                    
                    formats = data.get('formatStreams', []) + data.get('adaptiveFormats', [])
                    
                    if formats:
                        # Get best quality video
                        best_format = None
                        for fmt in formats:
                            if fmt.get('container') == 'mp4' and 'video' in fmt.get('type', ''):
                                if not best_format or fmt.get('size', 0) > best_format.get('size', 0):
                                    best_format = fmt
                        
                        if not best_format and formats:
                            best_format = formats[0]
                        
                        if best_format:
                            return {
                                "success": True,
                                "download_url": best_format.get('url'),
                                "title": data.get('title', 'Video'),
                                "thumbnail": data.get('videoThumbnails', [{}])[0].get('url', ''),
                                "duration": data.get('lengthSeconds', 0),
                                "uploader": data.get('author', 'Unknown'),
                                "view_count": data.get('viewCount', 0),
                                "description": data.get('description', ''),
                                "method": f"invidious ({instance})"
                            }
            
        except Exception as e:
            logger.error(f"Invidious {instance} error: {e}")
            continue
    
    return {"success": False}

async def download_from_social_download(url: str) -> dict:
    """Try social-download.com API"""
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            # Social Download API endpoint
            api_url = "https://social-download-all-in-one.p.rapidapi.com/v1/social/autolink"
            
            # Try without API key first (some free endpoints exist)
            response = await client.post(
                "https://api.vevioz.com/@api/button/videos",
                data={"url": url},
                headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
                    "Content-Type": "application/x-www-form-urlencoded"
                }
            )
            
            if response.status_code == 200:
                result = response.json()
                if result.get('video'):
                    return {
                        "success": True,
                        "download_url": result['video'][0]['url'],
                        "title": result.get('title', 'Video'),
                        "method": "vevioz"
                    }
        
        return {"success": False}
    except Exception as e:
        logger.error(f"Social download error: {e}")
        return {"success": False}

async def download_from_y2mate_api(video_id: str) -> dict:
    """Try Y2mate API endpoints"""
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            # Y2mate-style API
            api_endpoints = [
                f"https://www.y2mate.com/mates/analyzeV2/ajax",
                f"https://api.y2mate.com/api/ajaxConvert/convert"
            ]
            
            for endpoint in api_endpoints:
                try:
                    response = await client.post(
                        endpoint,
                        data={
                            "k_query": f"https://www.youtube.com/watch?v={video_id}",
                            "k_page": "home",
                            "hl": "en",
                            "q_auto": 0
                        },
                        headers={
                            "User-Agent": "Mozilla/5.0",
                            "Content-Type": "application/x-www-form-urlencoded"
                        }
                    )
                    
                    if response.status_code == 200:
                        result = response.json()
                        if result.get('status') == 'ok':
                            return {
                                "success": True,
                                "data": result,
                                "method": "y2mate-api"
                            }
                except:
                    continue
        
        return {"success": False}
    except Exception as e:
        logger.error(f"Y2mate API error: {e}")
        return {"success": False}

@app.get("/")
async def root():
    return {
        "message": "Social Media Downloader API v5.0",
        "status": "active",
        "methods": ["Invidious", "Vevioz", "Y2Mate API", "Multiple Fallbacks"]
    }

@app.get("/health")
async def health():
    return {"status": "healthy", "version": "5.0.0", "methods": ["invidious", "vevioz", "y2mate"]}

@app.get("/api/config")
async def get_config():
    return {
        "website_name": admin_config.get("website_name", "Social Media Downloader"),
        "tagline": admin_config.get("tagline", "Download videos"),
        "logo_url": admin_config.get("logo_url", ""),
        "adsense_code": admin_config.get("adsense_code", ""),
        "monetization_enabled": admin_config.get("monetization_enabled", False),
        "monetization_link": admin_config.get("monetization_link", ""),
        "monetization_clicks": admin_config.get("monetization_clicks", 2)
    }

@app.post("/api/info")
async def get_info(request: DownloadRequest):
    """Get video info using Invidious API"""
    try:
        video_id = extract_video_id(request.url)
        
        if not video_id:
            raise HTTPException(status_code=400, detail="Invalid YouTube URL")
        
        # Try Invidious first
        result = await download_from_invidious(video_id)
        
        if result.get("success"):
            return {
                "success": True,
                "data": {
                    "title": result.get("title", f"Video {video_id}"),
                    "thumbnail": result.get("thumbnail", f"https://img.youtube.com/vi/{video_id}/maxresdefault.jpg"),
                    "duration": result.get("duration", 0),
                    "uploader": result.get("uploader", "Unknown"),
                    "description": result.get("description", ""),
                    "view_count": result.get("view_count", 0),
                    "formats": [],
                    "webpage_url": request.url
                }
            }
        
        # Fallback to basic info
        return {
            "success": True,
            "data": {
                "title": f"Video {video_id}",
                "thumbnail": f"https://img.youtube.com/vi/{video_id}/maxresdefault.jpg",
                "duration": 0,
                "uploader": "Unknown",
                "description": "",
                "view_count": 0,
                "formats": [],
                "webpage_url": request.url
            }
        }
        
    except Exception as e:
        logger.error(f"Info error: {e}")
        raise HTTPException(status_code=400, detail=str(e))

@app.post("/api/download")
async def download(request: DownloadRequest):
    """Download with multiple fallback methods"""
    try:
        logger.info(f"Download request: {request.url}")
        
        video_id = extract_video_id(request.url)
        
        if not video_id:
            raise HTTPException(status_code=400, detail="Invalid YouTube URL")
        
        # Method 1: Try Invidious API (most reliable)
        logger.info(f"Trying Invidious for {video_id}")
        result = await download_from_invidious(video_id)
        
        if result.get("success") and result.get("download_url"):
            logger.info(f"Success via {result.get('method')}")
            return {
                "success": True,
                "type": "video",
                "data": {
                    "title": result.get("title", f"Video {video_id}"),
                    "download_url": result.get("download_url"),
                    "thumbnail": result.get("thumbnail", f"https://img.youtube.com/vi/{video_id}/maxresdefault.jpg"),
                    "duration": result.get("duration", 0),
                    "uploader": result.get("uploader", "Unknown"),
                    "view_count": result.get("view_count", 0),
                    "ext": "mp4",
                    "method": result.get("method", "invidious")
                }
            }
        
        # Method 2: Try Social Download
        logger.info("Trying Social Download")
        result = await download_from_social_download(request.url)
        
        if result.get("success") and result.get("download_url"):
            logger.info(f"Success via {result.get('method')}")
            return {
                "success": True,
                "type": "video",
                "data": {
                    "title": result.get("title", f"Video {video_id}"),
                    "download_url": result.get("download_url"),
                    "thumbnail": f"https://img.youtube.com/vi/{video_id}/maxresdefault.jpg",
                    "duration": 0,
                    "ext": "mp4",
                    "method": result.get("method", "social-download")
                }
            }
        
        # Method 3: Try Y2Mate API
        logger.info("Trying Y2Mate API")
        result = await download_from_y2mate_api(video_id)
        
        if result.get("success"):
            logger.info(f"Success via {result.get('method')}")
            return {
                "success": True,
                "type": "video",
                "data": {
                    "title": f"Video {video_id}",
                    "download_url": f"https://www.youtube.com/watch?v={video_id}",
                    "thumbnail": f"https://img.youtube.com/vi/{video_id}/maxresdefault.jpg",
                    "duration": 0,
                    "ext": "mp4",
                    "method": result.get("method", "y2mate"),
                    "note": "Processing... Please wait and try again in a few seconds"
                }
            }
        
        # All methods failed
        logger.error("All download methods failed")
        raise HTTPException(
            status_code=400, 
            detail="Unable to download this video. The video may be private, restricted, or unavailable."
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Download error: {str(e)}")
        raise HTTPException(status_code=400, detail=f"Failed to process: {str(e)}")

@app.post("/api/admin/login")
async def admin_login(creds: AdminLogin):
    password_hash = hashlib.sha256(creds.password.encode()).hexdigest()
    if creds.username == admin_config.get("username") and password_hash == admin_config.get("password_hash"):
        token = hashlib.sha256(f"{creds.username}{time.time()}".encode()).hexdigest()
        active_sessions[token] = {'username': creds.username, 'expires': datetime.now() + timedelta(hours=24)}
        return {"success": True, "token": token}
    raise HTTPException(status_code=401, detail="Invalid credentials")

@app.get("/ads.txt")
async def ads_txt():
    return HTMLResponse(content=admin_config.get('ads_txt', ''), media_type="text/plain")

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
