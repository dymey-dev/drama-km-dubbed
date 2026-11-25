#!/usr/bin/env python3
"""
FastAPI Backend for VANTA Dubbing Studio
Modular server supporting any drama episode, direct file uploads, local library browsing,
and sample-accurate timeline synthesis.
Author: VANTA
"""

import os
import sys
import re
import json
import time
import shutil
import asyncio
from pathlib import Path
from typing import List, Dict, Any, Optional

import uvicorn
from fastapi import FastAPI, HTTPException, UploadFile, File, Form, Request
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from studio_core import (
    discover_dramas, parse_srt, export_srt, separate_stems_demucs,
    safe_communicate_tts, process_single_line_audio,
    synthesize_dialogue_timeline, assemble_master_speech_buffer,
    mix_stems_and_mux_video, get_duration, get_media_info,
    smart_classify_characters, KHMER_VOICES, CHARACTER_PRESETS, DEFAULT_CHARACTERS
)

WORKSPACE_DIR = Path(r"D:\Code_Dev\storyreel\downloads\Dubbed")
DOWNLOADS_DIR = Path(r"D:\Code_Dev\storyreel\downloads")
COMPLETED_DIR = WORKSPACE_DIR / "completed"
COMPLETED_DIR.mkdir(parents=True, exist_ok=True)
MASTER_SPEECH_DIR = WORKSPACE_DIR / "master_speech"
MASTER_SPEECH_DIR.mkdir(parents=True, exist_ok=True)
SUBTITLES_DIR = WORKSPACE_DIR / "subtitles"
SUBTITLES_DIR.mkdir(parents=True, exist_ok=True)
TEMP_WORK_DIR = WORKSPACE_DIR / "studio_cache"
TEMP_WORK_DIR.mkdir(parents=True, exist_ok=True)
UPLOADS_DIR = WORKSPACE_DIR / "uploads"
UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
STATIC_DIR = WORKSPACE_DIR / "static"
STATIC_DIR.mkdir(parents=True, exist_ok=True)

app = FastAPI(title="VANTA Dubbing Studio API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

STUDIO_STATE = {
    "video_path": None,
    "subtitle_path": None,
    "subtitle_data": [],
    "stem_vocals": None,
    "stem_bgm": None,
    "master_speech_wav": None,
    "dubbed_video_path": None,
    "progress_status": "Ready",
    "is_processing": False
}

# ----------------- Request Models -----------------

class LoadFileRequest(BaseModel):
    video_path: str
    subtitle_path: Optional[str] = None

class PasteSubtitlesRequest(BaseModel):
    raw_text: str

class SaveSubtitlesRequest(BaseModel):
    lines: List[Dict[str, Any]]

class AutoClassifyRequest(BaseModel):
    lines: Optional[List[Dict[str, Any]]] = None

class AuditionRequest(BaseModel):
    line_idx: int
    khmer_text: str
    voice: Optional[str] = "km-KH-PisethNeural"
    pitch: Optional[str] = "-2Hz"
    rate: Optional[str] = "+0%"

class RemixRequest(BaseModel):
    voice_boost: float = 2.2
    bgm_volume: float = 0.22
    duck_ratio: float = 6.0
    duck_attack: int = 15
    duck_release: int = 250
    limiter_peak: float = 0.95

class PipelineRequest(BaseModel):
    lines: List[Dict[str, Any]]
    characters: Dict[str, Dict[str, str]]
    voice_boost: float = 2.2
    bgm_volume: float = 0.22
    duck_ratio: float = 6.0
    duck_attack: int = 15
    duck_release: int = 250
    limiter_peak: float = 0.95

# ----------------- Endpoints -----------------

@app.get("/api/library")
def get_library():
    """
    Returns dramas and episodes grouped cleanly so user can pick Ep 01, Ep 02, etc. with 1 click.
    """
    dramas = {}
    if not DOWNLOADS_DIR.exists():
        return []

    for item in DOWNLOADS_DIR.iterdir():
        if item.is_dir() and item.name != "Dubbed":
            series_name = item.name
            dramas[series_name] = []
            
            # Find all video files
            vids = sorted(list(item.glob("*.mp4")) + list(item.glob("*.mkv")))
            for v in vids:
                # Find matching subtitle (srt or txt)
                ep_match = re.search(r'(?:ep|ep_)?(\d+)', v.name, re.IGNORECASE)
                ep_num = int(ep_match.group(1)) if ep_match else None
                
                # Check for srt or txt (prioritize edited subtitles in subtitles/)
                sub_candidates = []
                if ep_num is not None:
                    sub_candidates = list(SUBTITLES_DIR.glob(f"*ep*{ep_num}*.srt")) + \
                                     list(SUBTITLES_DIR.glob(f"*Ep_{ep_num:02d}*.srt")) + \
                                     list(item.glob(f"*ep*{ep_num}*km*.txt")) + \
                                     list(item.glob(f"*ep*{ep_num}*km*.srt")) + \
                                     list(item.glob(f"*ep*{ep_num}*.srt"))
                if not sub_candidates:
                    sub_candidates = list(SUBTITLES_DIR.glob(f"{v.stem}*.srt")) + \
                                     list(item.glob(f"{v.stem}*.srt")) + \
                                     list(item.glob(f"{v.stem}*.txt"))

                sub_file = sub_candidates[0] if sub_candidates else None
                
                # Check stems
                stem_dir = WORKSPACE_DIR / "stems" / v.stem
                has_stems = (stem_dir / "no_vocals.wav").exists()
                
                # Check completed dubbed video
                has_dubbed = False
                dubbed_cand = COMPLETED_DIR / f"{v.stem}_Khmer_Dubbed.mp4"
                if dubbed_cand.exists():
                    has_dubbed = True
                elif ep_num is not None:
                    ep_cands = list(COMPLETED_DIR.glob(f"*ep*{ep_num}*Khmer_Dubbed.mp4")) + \
                               list(COMPLETED_DIR.glob(f"*Ep_{ep_num:02d}*Khmer_Dubbed.mp4"))
                    if ep_cands:
                        has_dubbed = True
                elif (WORKSPACE_DIR / f"{v.stem}_Khmer_Dubbed.mp4").exists():
                    has_dubbed = True

                dramas[series_name].append({
                    "episode": f"EP{ep_num:02d}" if ep_num is not None else v.stem,
                    "title": v.name,
                    "video_path": str(v),
                    "subtitle_path": str(sub_file) if sub_file else "",
                    "has_stems": has_stems,
                    "has_dubbed": has_dubbed
                })

    # Also check Dubbed root
    dubbed_vids = list(WORKSPACE_DIR.glob("EP*.mp4"))
    if dubbed_vids:
        dramas["Dubbed Root"] = []
        for v in dubbed_vids:
            if "_Khmer_Dubbed" not in v.name:
                has_d = (COMPLETED_DIR / f"{v.stem}_Khmer_Dubbed.mp4").exists() or \
                        (WORKSPACE_DIR / f"{v.stem}_Khmer_Dubbed.mp4").exists()
                dramas["Dubbed Root"].append({
                    "episode": v.stem,
                    "title": v.name,
                    "video_path": str(v),
                    "subtitle_path": "",
                    "has_stems": (WORKSPACE_DIR / "stems" / v.stem / "no_vocals.wav").exists(),
                    "has_dubbed": has_d
                })

    # Format into grouped array
    result = []
    for s_name, eps in dramas.items():
        if eps:
            result.append({
                "series": s_name,
                "episodes": eps
            })
    return result

def resolve_vocal_audio_path() -> Optional[Path]:
    """
    Resolves the best vocal audio track for acoustic analysis:
    1. Returns STUDIO_STATE['stem_vocals'] ONLY if it matches the current video
    2. Searches WORKSPACE_DIR/stems for matching stem vocals.wav
    3. If no Demucs stem exists, extracts quick preview audio directly from source video.
    """
    vid_path = STUDIO_STATE.get("video_path")
    if not vid_path or not vid_path.exists():
        return None

    # Check if existing stem_vocals actually belongs to this video
    voc = STUDIO_STATE.get("stem_vocals")
    if voc and Path(voc).exists():
        if vid_path.stem in str(voc):
            return Path(voc)
        m = re.search(r'(?:ep|ep_)?(\d+)', vid_path.name, re.IGNORECASE)
        if m and f"ep_{int(m.group(1)):02d}" in str(voc).lower():
            return Path(voc)
        # Stale stem from prior episode! Clear it
        STUDIO_STATE["stem_vocals"] = None
        STUDIO_STATE["stem_bgm"] = None

    # Check stems folder for this video stem
    stem_dir = WORKSPACE_DIR / "stems" / vid_path.stem
    if (stem_dir / "vocals.wav").exists():
        STUDIO_STATE["stem_vocals"] = stem_dir / "vocals.wav"
        if (stem_dir / "no_vocals.wav").exists():
            STUDIO_STATE["stem_bgm"] = stem_dir / "no_vocals.wav"
        return stem_dir / "vocals.wav"

    # Search by ep number in stems
    m = re.search(r'(?:ep|ep_)?(\d+)', vid_path.name, re.IGNORECASE)
    if m:
        ep_num = int(m.group(1))
        matches = list((WORKSPACE_DIR / "stems").glob(f"*ep*{ep_num}*")) + \
                  list((WORKSPACE_DIR / "stems").glob(f"*Ep_{ep_num:02d}*"))
        for cand in matches:
            if (cand / "vocals.wav").exists():
                STUDIO_STATE["stem_vocals"] = cand / "vocals.wav"
                if (cand / "no_vocals.wav").exists():
                    STUDIO_STATE["stem_bgm"] = cand / "no_vocals.wav"
                return cand / "vocals.wav"

    # Fallback: extract fast mono audio track directly from video
    preview_wav = TEMP_WORK_DIR / f"{vid_path.stem}_vocal_preview.wav"
    if not preview_wav.exists() or preview_wav.stat().st_size < 1000:
        try:
            subprocess.run([
                "ffmpeg", "-y", "-i", str(vid_path),
                "-vn", "-ar", "44100", "-ac", "1",
                "-af", "highpass=f=80,lowpass=f=5500",
                str(preview_wav)
            ], check=True, capture_output=True)
        except Exception:
            return None

    if preview_wav.exists() and preview_wav.stat().st_size > 1000:
        return preview_wav

    return None

@app.post("/api/load_file")
def load_file(req: LoadFileRequest):
    vid_path = Path(req.video_path)
    if not vid_path.exists():
        raise HTTPException(status_code=404, detail=f"Video file not found: {req.video_path}")

    # Reset episode-specific state when switching videos
    prev_vid = STUDIO_STATE.get("video_path")
    if prev_vid is None or Path(prev_vid).resolve() != vid_path.resolve():
        STUDIO_STATE["stem_vocals"] = None
        STUDIO_STATE["stem_bgm"] = None
        STUDIO_STATE["master_speech_wav"] = None
        STUDIO_STATE["dubbed_video_path"] = None
        STUDIO_STATE["subtitle_data"] = []

    STUDIO_STATE["video_path"] = vid_path
    
    # Resolve stems and vocal track
    voc_path = resolve_vocal_audio_path()

    # Resolve subtitles
    sub_path = Path(req.subtitle_path) if req.subtitle_path else None
    
    # If not provided, search smart
    if not sub_path or not sub_path.exists():
        parent_dir = vid_path.parent
        # Look for ep number
        m = re.search(r'(?:ep|ep_)?(\d+)', vid_path.name, re.IGNORECASE)
        ep_num = int(m.group(1)) if m else None
        
        candidates = []
        if ep_num:
            candidates += list(parent_dir.glob(f"*ep*{ep_num}*km*.txt")) + \
                          list(parent_dir.glob(f"*ep*{ep_num}*km*.srt")) + \
                          list(parent_dir.glob(f"*ep*{ep_num}*_subtitles*.srt"))
        candidates += list(parent_dir.glob(f"{vid_path.stem}*.srt")) + list(parent_dir.glob(f"{vid_path.stem}*.txt"))

        for c in candidates:
            if c.exists() and c.is_file():
                sub_path = c
                break

    STUDIO_STATE["subtitle_path"] = sub_path

    # Parse subtitle & auto-classify using acoustic vocal analysis
    parsed_lines = parse_srt(sub_path) if sub_path and sub_path.exists() else []
    if parsed_lines:
        parsed_lines = smart_classify_characters(parsed_lines, vocals_path=voc_path)
    STUDIO_STATE["subtitle_data"] = parsed_lines

    # Check dubbed output in completed/ first
    dubbed_cand = COMPLETED_DIR / f"{vid_path.stem}_Khmer_Dubbed.mp4"
    if not dubbed_cand.exists() and vid_path.name == "EP01.mp4":
        dubbed_cand = COMPLETED_DIR / "EP01_Khmer_Dubbed.mp4"
    if not dubbed_cand.exists():
        # Search by ep number
        m = re.search(r'(?:ep|ep_)?(\d+)', vid_path.name, re.IGNORECASE)
        if m:
            ep_num = int(m.group(1))
            ep_cands = list(COMPLETED_DIR.glob(f"*ep*{ep_num}*Khmer_Dubbed.mp4")) + \
                       list(COMPLETED_DIR.glob(f"*Ep_{ep_num:02d}*Khmer_Dubbed.mp4"))
            if ep_cands:
                dubbed_cand = ep_cands[0]
    if not dubbed_cand.exists():
        fallback = WORKSPACE_DIR / f"{vid_path.stem}_Khmer_Dubbed.mp4"
        if fallback.exists():
            dubbed_cand = fallback
        elif (WORKSPACE_DIR / "EP01_Khmer_Dubbed.mp4").exists() and vid_path.name == "EP01.mp4":
            dubbed_cand = WORKSPACE_DIR / "EP01_Khmer_Dubbed.mp4"

    has_dubbed = dubbed_cand.exists()
    STUDIO_STATE["dubbed_video_path"] = dubbed_cand if has_dubbed else None

    # Check master speech wav (check master_speech/ first, fallback to root)
    speech_cand = MASTER_SPEECH_DIR / f"{vid_path.stem}_master_speech.wav"
    if not speech_cand.exists():
        fallback_speech = WORKSPACE_DIR / f"{vid_path.stem}_master_speech.wav"
        if fallback_speech.exists():
            speech_cand = fallback_speech
        elif vid_path.name == "EP01.mp4" and (WORKSPACE_DIR / "master_khmer_speech.wav").exists():
            speech_cand = WORKSPACE_DIR / "master_khmer_speech.wav"
    STUDIO_STATE["master_speech_wav"] = speech_cand if speech_cand.exists() else None

    dur = get_duration(vid_path)

    return {
        "status": "success",
        "video_name": vid_path.name,
        "video_path": str(vid_path),
        "video_duration": dur,
        "subtitle_name": sub_path.name if sub_path else "None",
        "subtitle_path": str(sub_path) if sub_path else "",
        "lines_count": len(parsed_lines),
        "has_stems": STUDIO_STATE["stem_bgm"] is not None and STUDIO_STATE["stem_bgm"].exists(),
        "has_dubbed": has_dubbed,
        "subtitles": parsed_lines
    }

@app.post("/api/upload_video")
async def upload_video(file: UploadFile = File(...)):
    save_path = UPLOADS_DIR / file.filename
    with open(save_path, "wb") as f:
        shutil.copyfileobj(file.file, f)
    return load_file(LoadFileRequest(video_path=str(save_path)))

@app.post("/api/upload_subtitle")
async def upload_subtitle(file: UploadFile = File(...)):
    save_path = UPLOADS_DIR / file.filename
    with open(save_path, "wb") as f:
        shutil.copyfileobj(file.file, f)
    
    parsed = parse_srt(save_path)
    STUDIO_STATE["subtitle_path"] = save_path
    STUDIO_STATE["subtitle_data"] = parsed
    return {
        "status": "success",
        "subtitle_name": save_path.name,
        "lines_count": len(parsed),
        "subtitles": parsed
    }

@app.post("/api/paste_subtitles")
def paste_subtitles(req: PasteSubtitlesRequest):
    temp_txt = TEMP_WORK_DIR / "pasted_subtitles.txt"
    with open(temp_txt, "w", encoding="utf-8") as f:
        f.write(req.raw_text)
    
    parsed = parse_srt(temp_txt)
    if parsed:
        voc_p = resolve_vocal_audio_path()
        parsed = smart_classify_characters(parsed, vocals_path=voc_p)
    STUDIO_STATE["subtitle_data"] = parsed
    return {
        "status": "success",
        "lines_count": len(parsed),
        "subtitles": parsed
    }

@app.post("/api/save_subtitles")
def save_subtitles(req: SaveSubtitlesRequest):
    if not STUDIO_STATE["video_path"]:
        raise HTTPException(status_code=400, detail="No video loaded")

    updated_items = []
    for item in req.lines:
        s_sec = item.get("start_sec", 0.0)
        e_sec = item.get("end_sec", s_sec + item.get("duration", 2.0))
        updated_items.append({
            "idx": int(item["idx"]),
            "start": item["start"],
            "end": item["end"],
            "start_sec": s_sec,
            "end_sec": e_sec,
            "duration": round(e_sec - s_sec, 2),
            "speaker": item.get("speaker", "Male Lead"),
            "text": item.get("text", "") or item.get("khmer_text", "")
        })

    STUDIO_STATE["subtitle_data"] = updated_items
    save_path = SUBTITLES_DIR / f"{STUDIO_STATE['video_path'].stem}_edited_km.srt"
    export_srt(updated_items, save_path)
    STUDIO_STATE["subtitle_path"] = save_path

    return {"status": "saved", "path": f"subtitles/{save_path.name}", "count": len(updated_items)}

@app.get("/api/presets")
def get_presets():
    return {
        "presets": CHARACTER_PRESETS,
        "voices": KHMER_VOICES
    }

@app.post("/api/auto_classify")
def auto_classify_endpoint(req: AutoClassifyRequest):
    lines = req.lines or STUDIO_STATE["subtitle_data"]
    if not lines:
        raise HTTPException(status_code=400, detail="No dialogue lines available to classify")
    
    vocals_p = resolve_vocal_audio_path()
    classified = smart_classify_characters(lines, vocals_path=vocals_p)
    STUDIO_STATE["subtitle_data"] = classified

    # Compute breakdown statistics
    stats = {}
    for l in classified:
        spk = l.get("speaker", "Male Lead")
        stats[spk] = stats.get(spk, 0) + 1

    return {
        "status": "success",
        "lines": classified,
        "count": len(classified),
        "stats": stats
    }

@app.get("/api/completed")
def get_completed_videos():
    items = []
    if not COMPLETED_DIR.exists():
        return items
    vids = sorted(list(COMPLETED_DIR.glob("*.mp4")), key=lambda p: p.stat().st_mtime, reverse=True)
    for v in vids:
        size_mb = v.stat().st_size / (1024 * 1024)
        mtime = time.strftime("%Y-%m-%d %H:%M", time.localtime(v.stat().st_mtime))
        items.append({
            "name": v.name,
            "path": str(v),
            "size_mb": round(size_mb, 1),
            "modified": mtime,
            "url": f"/media/completed/{v.name}"
        })
    return items

@app.get("/media/completed/{filename}")
def stream_completed_file(filename: str):
    target = COMPLETED_DIR / filename
    if not target.exists():
        raise HTTPException(status_code=404, detail="Completed video file not found")
    return FileResponse(str(target), media_type="video/mp4")

@app.post("/api/audition")
async def audition_line(req: AuditionRequest):
    text = req.khmer_text.strip()
    if not text:
        raise HTTPException(status_code=400, detail="Empty text")

    voice = req.voice or "km-KH-PisethNeural"
    pitch = req.pitch or "-2Hz"
    rate = req.rate or "+0%"

    out_mp3 = TEMP_WORK_DIR / f"audition_{req.line_idx}.mp3"
    await safe_communicate_tts(text, voice, rate, pitch, "+0%", out_mp3)

    return {"status": "success", "audio_url": f"/media/audition?idx={req.line_idx}&t={time.time()}"}

@app.post("/api/separate_stems")
def separate_stems_endpoint():
    vid_path = STUDIO_STATE["video_path"]
    if not vid_path or not vid_path.exists():
        raise HTTPException(status_code=400, detail="No video loaded")

    STUDIO_STATE["is_processing"] = True
    STUDIO_STATE["progress_status"] = "Isolating BGM & Dialogue Stems (Demucs)..."

    try:
        vocals, no_vocals = separate_stems_demucs(vid_path, WORKSPACE_DIR)
        STUDIO_STATE["stem_vocals"] = vocals
        STUDIO_STATE["stem_bgm"] = no_vocals
        STUDIO_STATE["progress_status"] = "Stems Ready"
        STUDIO_STATE["is_processing"] = False
        return {"status": "success", "has_stems": True}
    except Exception as ex:
        STUDIO_STATE["is_processing"] = False
        STUDIO_STATE["progress_status"] = f"Error: {str(ex)}"
        raise HTTPException(status_code=500, detail=str(ex))

@app.post("/api/remix")
def remix_endpoint(req: RemixRequest):
    vid_path = STUDIO_STATE["video_path"]
    bgm_path = STUDIO_STATE["stem_bgm"]
    speech_path = STUDIO_STATE["master_speech_wav"]

    if not vid_path or not vid_path.exists():
        raise HTTPException(status_code=400, detail="No video loaded")
    if not bgm_path or not bgm_path.exists():
        raise HTTPException(status_code=400, detail="BGM stem not ready. Run stem separation first.")
    if not speech_path or not speech_path.exists():
        raise HTTPException(status_code=400, detail="Master speech track not generated. Run Full Dubbing first.")

    out_vid = COMPLETED_DIR / f"{vid_path.stem}_Khmer_Dubbed.mp4"

    mix_stems_and_mux_video(
        video_in=vid_path,
        bgm_wav=bgm_path,
        speech_wav=speech_path,
        video_out=out_vid,
        voice_boost=req.voice_boost,
        bgm_volume=req.bgm_volume,
        duck_ratio=req.duck_ratio,
        duck_attack=req.duck_attack,
        duck_release=req.duck_release,
        limiter_peak=req.limiter_peak
    )

    STUDIO_STATE["dubbed_video_path"] = out_vid

    return {
        "status": "success",
        "dubbed_url": f"/media/dubbed_video?t={time.time()}",
        "message": "Re-Mix Complete"
    }

@app.post("/api/run_pipeline")
async def run_pipeline_endpoint(req: PipelineRequest):
    vid_path = STUDIO_STATE["video_path"]
    if not vid_path or not vid_path.exists():
        raise HTTPException(status_code=400, detail="No video loaded")

    STUDIO_STATE["is_processing"] = True
    STUDIO_STATE["progress_status"] = "Starting Pipeline..."

    # 1. Stems (Ensure stem belongs to current video)
    bgm_path = STUDIO_STATE.get("stem_bgm")
    needs_demucs = False
    if not bgm_path or not Path(bgm_path).exists():
        needs_demucs = True
    else:
        # Check stem ownership
        m = re.search(r'(?:ep|ep_)?(\d+)', vid_path.name, re.IGNORECASE)
        ep_sig = f"ep_{int(m.group(1)):02d}" if m else vid_path.stem.lower()
        if ep_sig not in str(bgm_path).lower() and vid_path.stem not in str(bgm_path):
            needs_demucs = True

    if needs_demucs:
        STUDIO_STATE["progress_status"] = "Separating Stems with Demucs..."
        vocals, no_vocals = separate_stems_demucs(vid_path, WORKSPACE_DIR)
        STUDIO_STATE["stem_vocals"] = vocals
        STUDIO_STATE["stem_bgm"] = no_vocals
        bgm_path = no_vocals

    # 2. Synthesis
    STUDIO_STATE["progress_status"] = "Synthesizing Khmer dialogue lines..."
    synth_temp = TEMP_WORK_DIR / vid_path.stem
    items = req.lines or STUDIO_STATE["subtitle_data"]
    STUDIO_STATE["subtitle_data"] = items

    dub_items = await synthesize_dialogue_timeline(
        items=items,
        character_map=req.characters,
        temp_dir=synth_temp
    )

    # 3. Assemble speech master
    STUDIO_STATE["progress_status"] = "Assembling sample-accurate master speech track..."
    total_dur = get_duration(vid_path)
    speech_master = MASTER_SPEECH_DIR / f"{vid_path.stem}_master_speech.wav"
    assemble_master_speech_buffer(dub_items, total_dur, speech_master)
    STUDIO_STATE["master_speech_wav"] = speech_master

    # 4. Mix & Mux
    STUDIO_STATE["progress_status"] = "Mastering audio with sidechain ducking & muxing video..."
    out_vid = COMPLETED_DIR / f"{vid_path.stem}_Khmer_Dubbed.mp4"

    mix_stems_and_mux_video(
        video_in=vid_path,
        bgm_wav=bgm_path,
        speech_wav=speech_master,
        video_out=out_vid,
        voice_boost=req.voice_boost,
        bgm_volume=req.bgm_volume,
        duck_ratio=req.duck_ratio,
        duck_attack=req.duck_attack,
        duck_release=req.duck_release,
        limiter_peak=req.limiter_peak
    )

    STUDIO_STATE["dubbed_video_path"] = out_vid
    STUDIO_STATE["is_processing"] = False
    STUDIO_STATE["progress_status"] = "Dubbing Complete!"

    return {
        "status": "success",
        "dubbed_url": f"/media/dubbed_video?t={time.time()}",
        "speech_wav_url": f"/media/speech_wav?t={time.time()}"
    }

# ----------------- Media Streaming Endpoints -----------------

NO_CACHE_HEADERS = {
    "Cache-Control": "no-cache, no-store, must-revalidate",
    "Pragma": "no-cache",
    "Expires": "0"
}

@app.get("/media/source_video")
def get_source_video():
    p = STUDIO_STATE["video_path"]
    if not p or not p.exists():
        raise HTTPException(status_code=404, detail="No source video")
    return FileResponse(str(p), media_type="video/mp4", headers=NO_CACHE_HEADERS)

@app.get("/media/dubbed_video")
def get_dubbed_video():
    p = STUDIO_STATE["dubbed_video_path"]
    if not p or not p.exists():
        raise HTTPException(status_code=404, detail="Dubbed video not ready")
    return FileResponse(str(p), media_type="video/mp4", headers=NO_CACHE_HEADERS)

@app.get("/media/bgm_audio")
def get_bgm_audio():
    p = STUDIO_STATE["stem_bgm"]
    if not p or not p.exists():
        raise HTTPException(status_code=404, detail="BGM stem not ready")
    return FileResponse(str(p), media_type="audio/wav", headers=NO_CACHE_HEADERS)

@app.get("/media/speech_wav")
def get_speech_audio():
    p = STUDIO_STATE["master_speech_wav"]
    if not p or not p.exists():
        raise HTTPException(status_code=404, detail="Speech master not ready")
    return FileResponse(str(p), media_type="audio/wav", headers=NO_CACHE_HEADERS)

@app.get("/media/audition")
def get_audition_audio(idx: int):
    p = TEMP_WORK_DIR / f"audition_{idx}.mp3"
    if not p.exists():
        raise HTTPException(status_code=404, detail="Audition file not found")
    return FileResponse(str(p), media_type="audio/mpeg")

app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

@app.get("/", response_class=HTMLResponse)
def index_page():
    index_file = STATIC_DIR / "index.html"
    if index_file.exists():
        with open(index_file, "r", encoding="utf-8") as f:
            return f.read()
    return "<h1>VANTA Dubbing Studio - static/index.html not found</h1>"

if __name__ == "__main__":
    uvicorn.run("server:app", host="0.0.0.0", port=7860, reload=False)
