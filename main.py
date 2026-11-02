from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, HTMLResponse
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

app = FastAPI(title="Social Media Downloader API", version="3.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Admin config
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

@app.get("/")
async def root():
    return {
        "message": "Social Media Downloader API v3.0",
        "status": "active",
        "method": "Cobalt API (NO yt-dlp)"
    }

@app.get("/health")
async def health():
    return {"status": "healthy", "version": "3.0.0"}

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
    return {
        "success": True,
        "data": {
            "title": "Video",
            "thumbnail": "",
            "duration": 0,
            "uploader": "Unknown",
            "description": "",
            "view_count": 0,
            "formats": [],
            "webpage_url": request.url
        }
    }

@app.post("/api/download")
async def download(request: DownloadRequest):
    try:
        logger.info(f"Download request: {request.url}")
        
        async with httpx.AsyncClient(timeout=30.0) as client:
            payload = {
                "url": request.url,
                "vCodec": "h264",
                "vQuality": "1080",
                "aFormat": "mp3" if request.format == "audio" else "best",
                "isAudioOnly": request.format == "audio"
            }
            
            response = await client.post(
                "https://api.cobalt.tools/api/json",
                json=payload,
                headers={"Accept": "application/json", "Content-Type": "application/json"}
            )
            
            if response.status_code == 200:
                data = response.json()
                logger.info(f"Cobalt response: {data}")
                
                if data.get('status') in ['stream', 'redirect']:
                    return {
                        "success": True,
                        "type": "video" if request.format != "audio" else "audio",
                        "data": {
                            "title": "Video",
                            "download_url": data.get('url'),
                            "thumbnail": "",
                            "duration": 0,
                            "ext": "mp4"
                        }
                    }
                elif data.get('status') == 'picker':
                    picker = data.get('picker', [])
                    if picker:
                        return {
                            "success": True,
                            "type": "video",
                            "data": {
                                "title": "Video",
                                "download_url": picker[0].get('url'),
                                "thumbnail": picker[0].get('thumb', ''),
                                "duration": 0,
                                "ext": "mp4"
                            }
                        }
        
        raise HTTPException(status_code=400, detail="Download failed. Try another video.")
        
    except Exception as e:
        logger.error(f"Error: {str(e)}")
        raise HTTPException(status_code=400, detail=str(e))

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
