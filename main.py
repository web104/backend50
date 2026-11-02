from fastapi import FastAPI, HTTPException, Request, Depends, Form, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, HTMLResponse, RedirectResponse
from pydantic import BaseModel
from typing import Optional, Dict, Any
import httpx
import requests
import os
import logging
import hashlib
import json
import time
import re
from datetime import datetime, timedelta
from pathlib import Path

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Social Media Downloader API",
    description="All-in-One Video & Thumbnail Downloader - No yt-dlp",
    version="3.0.0"
)

# CORS Configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Admin Configuration Storage
ADMIN_CONFIG_FILE = "admin_config.json"
CACHE_DIR = "cache"
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

Path(CACHE_DIR).mkdir(exist_ok=True)

def load_admin_config():
    if os.path.exists(ADMIN_CONFIG_FILE):
        try:
            with open(ADMIN_CONFIG_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except:
            return DEFAULT_ADMIN.copy()
    return DEFAULT_ADMIN.copy()

def save_admin_config(config):
    with open(ADMIN_CONFIG_FILE, 'w', encoding='utf-8') as f:
        json.dump(config, f, indent=2, ensure_ascii=False)

admin_config = load_admin_config()
active_sessions = {}

class DownloadRequest(BaseModel):
    url: str
    format: str = "best"

class AdminLogin(BaseModel):
    username: str
    password: str

class AdminUpdate(BaseModel):
    website_name: Optional[str] = None
    tagline: Optional[str] = None
    logo_url: Optional[str] = None
    adsense_code: Optional[str] = None
    ads_txt: Optional[str] = None
    monetization_enabled: Optional[bool] = None
    monetization_link: Optional[str] = None
    monetization_clicks: Optional[int] = None

class PasswordChange(BaseModel):
    old_password: str
    new_password: str

def verify_session(session_token: Optional[str]):
    if not session_token or session_token not in active_sessions:
        raise HTTPException(status_code=401, detail="Unauthorized")
    session_data = active_sessions[session_token]
    if datetime.now() > session_data['expires']:
        del active_sessions[session_token]
        raise HTTPException(status_code=401, detail="Session expired")
    return session_data

def extract_video_id(url: str, platform: str) -> Optional[str]:
    """Extract video ID from URL"""
    if platform == "youtube":
        patterns = [
            r'(?:youtube\.com\/watch\?v=|youtu\.be\/)([^&\n?#]+)',
            r'youtube\.com\/embed\/([^&\n?#]+)',
            r'youtube\.com\/v\/([^&\n?#]+)'
        ]
        for pattern in patterns:
            match = re.search(pattern, url)
            if match:
                return match.group(1)
    elif platform == "instagram":
        match = re.search(r'instagram\.com\/(?:p|reel|tv)\/([^\/\?]+)', url)
        if match:
            return match.group(1)
    elif platform == "tiktok":
        match = re.search(r'tiktok\.com\/@[\w\.]+\/video\/(\d+)', url)
        if match:
            return match.group(1)
    return None

def detect_platform(url: str) -> str:
    """Detect platform from URL"""
    if 'youtube.com' in url or 'youtu.be' in url:
        return 'youtube'
    elif 'instagram.com' in url:
        return 'instagram'
    elif 'tiktok.com' in url:
        return 'tiktok'
    elif 'facebook.com' in url or 'fb.watch' in url:
        return 'facebook'
    elif 'twitter.com' in url or 'x.com' in url:
        return 'twitter'
    return 'unknown'

async def download_with_cobalt(url: str, format_type: str = "best") -> Dict:
    """Download using Cobalt API - supports all major platforms"""
    try:
        logger.info(f"Cobalt API: Processing {url}")
        
        async with httpx.AsyncClient(timeout=30.0) as client:
            payload = {
                "url": url,
                "vCodec": "h264",
                "vQuality": "1080",
                "aFormat": "mp3" if format_type == "audio" else "best",
                "isAudioOnly": format_type == "audio",
                "filenamePattern": "basic"
            }
            
            response = await client.post(
                "https://api.cobalt.tools/api/json",
                json=payload,
                headers={
                    "Accept": "application/json",
                    "Content-Type": "application/json"
                }
            )
            
            if response.status_code == 200:
                data = response.json()
                logger.info(f"Cobalt response: {data}")
                
                if data.get('status') in ['stream', 'redirect']:
                    download_url = data.get('url')
                    if download_url:
                        return {
                            "success": True,
                            "download_url": download_url,
                            "title": "Video",
                            "thumbnail": "",
                            "source": "cobalt"
                        }
                elif data.get('status') == 'picker':
                    # Multiple formats available
                    picker = data.get('picker', [])
                    if picker:
                        return {
                            "success": True,
                            "download_url": picker[0].get('url'),
                            "title": "Video",
                            "thumbnail": picker[0].get('thumb', ''),
                            "source": "cobalt"
                        }
            
            logger.warning(f"Cobalt failed: Status {response.status_code}")
            return {"success": False, "error": "Cobalt API failed"}
            
    except Exception as e:
        logger.error(f"Cobalt error: {str(e)}")
        return {"success": False, "error": str(e)}

async def download_with_invidious(video_id: str, format_type: str = "best") -> Dict:
    """Download YouTube using Invidious API"""
    try:
        logger.info(f"Invidious API: Processing video {video_id}")
        
        instances = [
            "https://inv.riverside.rocks",
            "https://invidious.snopyta.org",
            "https://invidious.kavin.rocks"
        ]
        
        for instance in instances:
            try:
                async with httpx.AsyncClient(timeout=20.0) as client:
                    response = await client.get(f"{instance}/api/v1/videos/{video_id}")
                    
                    if response.status_code == 200:
                        data = response.json()
                        
                        # Get best format
                        formats = data.get('adaptiveFormats', [])
                        if not formats:
                            formats = data.get('formatStreams', [])
                        
                        if formats:
                            best_format = formats[0]
                            return {
                                "success": True,
                                "download_url": best_format.get('url', ''),
                                "title": data.get('title', 'Unknown'),
                                "thumbnail": data.get('videoThumbnails', [{}])[0].get('url', ''),
                                "duration": data.get('lengthSeconds', 0),
                                "source": "invidious"
                            }
            except:
                continue
        
        return {"success": False, "error": "All Invidious instances failed"}
        
    except Exception as e:
        logger.error(f"Invidious error: {str(e)}")
        return {"success": False, "error": str(e)}

async def download_with_y2mate(url: str) -> Dict:
    """Download using Y2Mate API"""
    try:
        logger.info(f"Y2Mate API: Processing {url}")
        # This is a placeholder - Y2Mate requires scraping
        return {"success": False, "error": "Y2Mate not implemented"}
    except Exception as e:
        return {"success": False, "error": str(e)}

@app.get("/")
async def root():
    return {
        "message": "Social Media Downloader API v3.0",
        "status": "active",
        "features": [
            "NO yt-dlp - Using Cobalt + Invidious APIs",
            "Multi-platform support",
            "Admin panel",
            "Monetization"
        ]
    }

@app.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "version": "3.0.0",
        "timestamp": datetime.now().isoformat(),
        "method": "Cobalt + Invidious APIs"
    }

@app.get("/api/config")
async def get_public_config():
    return {
        "website_name": admin_config.get("website_name", DEFAULT_ADMIN["website_name"]),
        "tagline": admin_config.get("tagline", DEFAULT_ADMIN["tagline"]),
        "logo_url": admin_config.get("logo_url", ""),
        "adsense_code": admin_config.get("adsense_code", ""),
        "monetization_enabled": admin_config.get("monetization_enabled", False),
        "monetization_link": admin_config.get("monetization_link", ""),
        "monetization_clicks": admin_config.get("monetization_clicks", 2)
    }

@app.post("/api/info")
async def get_video_info(request: DownloadRequest):
    """Get video info - using Cobalt + Invidious"""
    try:
        platform = detect_platform(request.url)
        logger.info(f"Platform detected: {platform}")
        
        # Try Cobalt first (works for all platforms)
        result = await download_with_cobalt(request.url, "best")
        if result.get("success"):
            return {
                "success": True,
                "data": {
                    "title": result.get("title", "Video"),
                    "thumbnail": result.get("thumbnail", ""),
                    "duration": 0,
                    "uploader": "Unknown",
                    "description": "",
                    "view_count": 0,
                    "formats": [],
                    "webpage_url": request.url
                }
            }
        
        # Try Invidious for YouTube
        if platform == 'youtube':
            video_id = extract_video_id(request.url, 'youtube')
            if video_id:
                result = await download_with_invidious(video_id, "best")
                if result.get("success"):
                    return {
                        "success": True,
                        "data": {
                            "title": result.get("title", "Video"),
                            "thumbnail": result.get("thumbnail", ""),
                            "duration": result.get("duration", 0),
                            "uploader": "Unknown",
                            "description": "",
                            "view_count": 0,
                            "formats": [],
                            "webpage_url": request.url
                        }
                    }
        
        raise HTTPException(status_code=400, detail="Could not fetch video info")
        
    except Exception as e:
        logger.error(f"Info error: {str(e)}")
        raise HTTPException(status_code=400, detail=str(e))

@app.post("/api/download")
async def get_download_url(request: DownloadRequest):
    """Download video - using Cobalt + Invidious APIs ONLY"""
    try:
        platform = detect_platform(request.url)
        logger.info(f"Download request for {platform}: {request.url}")
        
        # Method 1: Cobalt API (Primary - works for everything)
        result = await download_with_cobalt(request.url, request.format)
        if result.get("success"):
            return {
                "success": True,
                "type": "video" if request.format != "audio" else "audio",
                "data": {
                    "title": result.get("title", "Video"),
                    "download_url": result.get("download_url"),
                    "thumbnail": result.get("thumbnail", ""),
                    "duration": result.get("duration", 0),
                    "ext": "mp4" if request.format != "audio" else "mp3"
                }
            }
        
        # Method 2: Invidious for YouTube
        if platform == 'youtube':
            video_id = extract_video_id(request.url, 'youtube')
            if video_id:
                logger.info(f"Trying Invidious for video: {video_id}")
                result = await download_with_invidious(video_id, request.format)
                if result.get("success"):
                    return {
                        "success": True,
                        "type": "video" if request.format != "audio" else "audio",
                        "data": {
                            "title": result.get("title", "Video"),
                            "download_url": result.get("download_url"),
                            "thumbnail": result.get("thumbnail", ""),
                            "duration": result.get("duration", 0),
                            "ext": "mp4" if request.format != "audio" else "mp3"
                        }
                    }
        
        # All methods failed
        raise HTTPException(
            status_code=400,
            detail="Download failed. Video may be private or restricted. Try another video."
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Download error: {str(e)}")
        raise HTTPException(status_code=400, detail=f"Download failed: {str(e)}")

# Admin endpoints (keeping them as is)
@app.post("/api/admin/login")
async def admin_login(credentials: AdminLogin):
    password_hash = hashlib.sha256(credentials.password.encode()).hexdigest()
    if (credentials.username == admin_config.get("username") and
        password_hash == admin_config.get("password_hash")):
        session_token = hashlib.sha256(f"{credentials.username}{time.time()}".encode()).hexdigest()
        active_sessions[session_token] = {
            'username': credentials.username,
            'expires': datetime.now() + timedelta(hours=24)
        }
        return {"success": True, "token": session_token}
    raise HTTPException(status_code=401, detail="Invalid credentials")

@app.get("/api/admin/config")
async def get_admin_config(session_token: Optional[str] = None):
    verify_session(session_token)
    config = admin_config.copy()
    config.pop('password_hash', None)
    return {"success": True, "config": config}

@app.post("/api/admin/config")
async def update_admin_config(update: AdminUpdate, session_token: Optional[str] = None):
    verify_session(session_token)
    if update.website_name is not None:
        admin_config['website_name'] = update.website_name
    if update.tagline is not None:
        admin_config['tagline'] = update.tagline
    if update.logo_url is not None:
        admin_config['logo_url'] = update.logo_url
    if update.adsense_code is not None:
        admin_config['adsense_code'] = update.adsense_code
    if update.ads_txt is not None:
        admin_config['ads_txt'] = update.ads_txt
    if update.monetization_enabled is not None:
        admin_config['monetization_enabled'] = update.monetization_enabled
    if update.monetization_link is not None:
        admin_config['monetization_link'] = update.monetization_link
    if update.monetization_clicks is not None:
        admin_config['monetization_clicks'] = update.monetization_clicks
    save_admin_config(admin_config)
    return {"success": True, "message": "Configuration updated"}

@app.post("/api/admin/password")
async def change_password(change: PasswordChange, session_token: Optional[str] = None):
    verify_session(session_token)
    old_hash = hashlib.sha256(change.old_password.encode()).hexdigest()
    if old_hash != admin_config.get('password_hash'):
        raise HTTPException(status_code=400, detail="Incorrect old password")
    new_hash = hashlib.sha256(change.new_password.encode()).hexdigest()
    admin_config['password_hash'] = new_hash
    save_admin_config(admin_config)
    return {"success": True, "message": "Password changed"}

@app.get("/api/cron/cleanup")
async def cron_cleanup(key: str):
    if key != admin_config.get('cron_secret', DEFAULT_ADMIN['cron_secret']):
        raise HTTPException(status_code=403, detail="Invalid key")
    deleted_count = 0
    if os.path.exists(CACHE_DIR):
        for file in os.listdir(CACHE_DIR):
            try:
                os.remove(os.path.join(CACHE_DIR, file))
                deleted_count += 1
            except:
                pass
    return {"success": True, "message": f"{deleted_count} files deleted", "timestamp": datetime.now().isoformat()}

@app.post("/api/admin/test-cron")
async def test_cron(session_token: Optional[str] = None):
    verify_session(session_token)
    cron_secret = admin_config.get('cron_secret', DEFAULT_ADMIN['cron_secret'])
    return {"success": True, "cron_url": f"/api/cron/cleanup?key={cron_secret}"}

@app.get("/ads.txt")
async def get_ads_txt():
    return HTMLResponse(content=admin_config.get('ads_txt', ''), media_type="text/plain")

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
