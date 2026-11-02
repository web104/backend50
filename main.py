from fastapi import FastAPI, HTTPException, Request, Depends, Form, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from typing import Optional, Dict, Any
import yt_dlp
import os
import logging
import hashlib
import json
import time
from datetime import datetime, timedelta
from pathlib import Path

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Social Media Downloader API",
    description="All-in-One Video & Thumbnail Downloader with Admin Panel",
    version="2.0.0"
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

# Ensure cache directory exists
Path(CACHE_DIR).mkdir(exist_ok=True)

# Load or create admin config
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

# Session management (simple in-memory for demo)
active_sessions = {}

# Models
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

# Auth Helper
def verify_session(session_token: Optional[str]):
    if not session_token or session_token not in active_sessions:
        raise HTTPException(status_code=401, detail="Unauthorized")
    session_data = active_sessions[session_token]
    if datetime.now() > session_data['expires']:
        del active_sessions[session_token]
        raise HTTPException(status_code=401, detail="Session expired")
    return session_data

# Root endpoint
@app.get("/")
async def root():
    return {
        "message": "Social Media Downloader API v2.0",
        "status": "active",
        "features": [
            "Multi-platform video download",
            "Admin panel",
            "SEO optimization",
            "AdSense integration",
            "Monetization options"
        ],
        "endpoints": {
            "/info": "GET video information",
            "/download": "POST to get download URL",
            "/admin": "Admin panel login",
            "/api/config": "Get public configuration"
        }
    }

@app.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "cache_items": len(os.listdir(CACHE_DIR)) if os.path.exists(CACHE_DIR) else 0
    }

# Public config endpoint for frontend
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

# Video info endpoint
@app.post("/api/info")
async def get_video_info(request: DownloadRequest):
    try:
        ydl_opts = {
            'quiet': True,
            'no_warnings': True,
            'extract_flat': False,
        }
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            logger.info(f"Extracting info for: {request.url}")
            info = ydl.extract_info(request.url, download=False)
            
            formats = []
            if 'formats' in info:
                for f in info['formats'][:15]:
                    formats.append({
                        'format_id': f.get('format_id', ''),
                        'ext': f.get('ext', ''),
                        'quality': f.get('format_note', 'unknown'),
                        'filesize': f.get('filesize', 0),
                    })
            
            return {
                "success": True,
                "data": {
                    "title": info.get('title', 'Unknown'),
                    "thumbnail": info.get('thumbnail', ''),
                    "duration": info.get('duration', 0),
                    "uploader": info.get('uploader', 'Unknown'),
                    "description": info.get('description', '')[:300],
                    "view_count": info.get('view_count', 0),
                    "formats": formats,
                    "webpage_url": info.get('webpage_url', request.url)
                }
            }
    except Exception as e:
        logger.error(f"Error extracting info: {str(e)}")
        raise HTTPException(status_code=400, detail=f"Failed to extract info: {str(e)}")

# Download endpoint
@app.post("/api/download")
async def get_download_url(request: DownloadRequest):
    try:
        ydl_opts = {
            'quiet': True,
            'no_warnings': True,
            'extract_flat': False,
        }
        
        if request.format == "audio":
            ydl_opts['format'] = 'bestaudio/best'
        elif request.format == "video":
            ydl_opts['format'] = 'bestvideo+bestaudio/best'
        elif request.format == "thumbnail":
            ydl_opts['skip_download'] = True
        else:
            ydl_opts['format'] = 'best'
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            logger.info(f"Processing download for: {request.url}")
            info = ydl.extract_info(request.url, download=False)
            
            if request.format == "thumbnail":
                return {
                    "success": True,
                    "type": "thumbnail",
                    "data": {
                        "title": info.get('title', 'Unknown'),
                        "thumbnail_url": info.get('thumbnail', ''),
                    }
                }
            
            # Get best format URL
            format_url = None
            if 'url' in info:
                format_url = info['url']
            elif 'formats' in info and len(info['formats']) > 0:
                format_url = info['formats'][0].get('url', '')
            
            return {
                "success": True,
                "type": "video" if request.format != "audio" else "audio",
                "data": {
                    "title": info.get('title', 'Unknown'),
                    "download_url": format_url,
                    "thumbnail": info.get('thumbnail', ''),
                    "duration": info.get('duration', 0),
                    "ext": info.get('ext', 'mp4')
                }
            }
                
    except Exception as e:
        logger.error(f"Error processing download: {str(e)}")
        raise HTTPException(status_code=400, detail=f"Failed to process: {str(e)}")

# Admin Login
@app.post("/api/admin/login")
async def admin_login(credentials: AdminLogin):
    password_hash = hashlib.sha256(credentials.password.encode()).hexdigest()
    
    if (credentials.username == admin_config.get("username", DEFAULT_ADMIN["username"]) and
        password_hash == admin_config.get("password_hash", DEFAULT_ADMIN["password_hash"])):
        
        # Create session
        session_token = hashlib.sha256(f"{credentials.username}{time.time()}".encode()).hexdigest()
        active_sessions[session_token] = {
            'username': credentials.username,
            'expires': datetime.now() + timedelta(hours=24)
        }
        
        return {
            "success": True,
            "token": session_token,
            "message": "Login successful"
        }
    
    raise HTTPException(status_code=401, detail="Invalid credentials")

# Admin Get Config
@app.get("/api/admin/config")
async def get_admin_config(session_token: Optional[str] = None):
    verify_session(session_token)
    config = admin_config.copy()
    config.pop('password_hash', None)
    return {"success": True, "config": config}

# Admin Update Config
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

# Admin Change Password
@app.post("/api/admin/password")
async def change_password(change: PasswordChange, session_token: Optional[str] = None):
    verify_session(session_token)
    
    old_hash = hashlib.sha256(change.old_password.encode()).hexdigest()
    if old_hash != admin_config.get('password_hash'):
        raise HTTPException(status_code=400, detail="Incorrect old password")
    
    new_hash = hashlib.sha256(change.new_password.encode()).hexdigest()
    admin_config['password_hash'] = new_hash
    save_admin_config(admin_config)
    
    return {"success": True, "message": "Password changed successfully"}

# Cron cleanup endpoint
@app.get("/api/cron/cleanup")
async def cron_cleanup(key: str):
    if key != admin_config.get('cron_secret', DEFAULT_ADMIN['cron_secret']):
        raise HTTPException(status_code=403, detail="Invalid key")
    
    # Clean cache directory
    deleted_count = 0
    if os.path.exists(CACHE_DIR):
        for file in os.listdir(CACHE_DIR):
            try:
                os.remove(os.path.join(CACHE_DIR, file))
                deleted_count += 1
            except:
                pass
    
    logger.info(f"Cron cleanup: {deleted_count} files deleted")
    
    return {
        "success": True,
        "message": f"Cleanup completed. {deleted_count} files deleted.",
        "timestamp": datetime.now().isoformat()
    }

# Test cron endpoint (for admin panel)
@app.post("/api/admin/test-cron")
async def test_cron(session_token: Optional[str] = None):
    verify_session(session_token)
    
    cron_secret = admin_config.get('cron_secret', DEFAULT_ADMIN['cron_secret'])
    test_url = f"/api/cron/cleanup?key={cron_secret}"
    
    return {
        "success": True,
        "cron_url": test_url,
        "message": "Use this URL in your cron service (e.g., cron-job.org)"
    }

# Ads.txt endpoint
@app.get("/ads.txt")
async def get_ads_txt():
    ads_content = admin_config.get('ads_txt', '')
    return HTMLResponse(content=ads_content, media_type="text/plain")

# Supported sites
@app.get("/api/supported-sites")
async def get_supported_sites():
    try:
        extractors = yt_dlp.extractor.gen_extractors()
        sites = list(set([e.IE_NAME for e in extractors if hasattr(e, 'IE_NAME')]))
        return {
            "success": True,
            "count": len(sites),
            "sites": sorted(sites)[:100]
        }
    except Exception as e:
        return {"success": False, "error": str(e)}

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
