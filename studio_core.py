#!/usr/bin/env python3
"""
Studio Core Engine for Khmer Drama Dubbing
Modular pipeline supporting any drama episode: stem separation, Edge-TTS prosody synthesis,
sample-accurate timeline assembly, and dynamic sidechain mixing.
Author: VANTA
"""

import os
import re
import sys
import json
import time
import wave
import asyncio
import subprocess
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple, Callable
import numpy as np

# Supported Edge-TTS Khmer Voices
KHMER_VOICES = {
    "Piseth (Male - Deep/Narrator)": "km-KH-PisethNeural",
    "Sreymom (Female - Expressive/Clear)": "km-KH-SreymomNeural"
}

# Default Character Cast Presets
CHARACTER_PRESETS = {
    "Male Lead": {
        "voice": "km-KH-PisethNeural",
        "pitch": "-2Hz",
        "rate": "+0%",
        "volume": "+0%",
        "description": "Lucas / Narrator - Calm, deep, resonant",
        "badge_class": "badge-primary text-white"
    },
    "Butler": {
        "voice": "km-KH-PisethNeural",
        "pitch": "-6Hz",
        "rate": "+1%",
        "volume": "+5%",
        "description": "Housekeeper / Butler - Grave, respectful, formal",
        "badge_class": "badge-secondary text-white"
    },
    "Mafia Donna": {
        "voice": "km-KH-SreymomNeural",
        "pitch": "-3Hz",
        "rate": "-2%",
        "volume": "+5%",
        "description": "Serafina Corleone - Commanding, sultry, authoritative",
        "badge_class": "badge-accent text-white"
    },
    "Mother": {
        "voice": "km-KH-SreymomNeural",
        "pitch": "+0Hz",
        "rate": "-3%",
        "volume": "+2%",
        "description": "Mother / Ex-Wife - Expressive, emotional, sharp",
        "badge_class": "badge-info text-white"
    },
    "Child": {
        "voice": "km-KH-SreymomNeural",
        "pitch": "+5Hz",
        "rate": "+6%",
        "volume": "+3%",
        "description": "Child / Kid - High-pitched, playful, delicate",
        "badge_class": "badge-warning text-black"
    }
}
DEFAULT_CHARACTERS = CHARACTER_PRESETS

# Classification Heuristic Rule Patterns
FEMALE_TAGS = ['female', 'woman', 'girl', 'donna', 'serafina', 'mother', 'wife', 'lady', 'ស្រី']
MALE_TAGS = ['male', 'man', 'lucas', 'narrator', 'guy', 'ប្រុស']
CHILD_TAGS = ['child', 'kid', 'boy', 'daughter', 'son', 'កូន', 'ក្មេង', 'តូច', 'អាល្អិត']
BUTLER_TAGS = ['butler', 'housekeeper', 'មេផ្ទះ']

CHILD_PATTERNS = [
    r'ឱ្យគាត់ចេញទៅ', r'អោយគាត់ចេញទៅ', r'ធ្វើបាបខ្ញុំ', r'ពូពូមុន', r'បញ្ចុកខ្ញុំ',
    r'ម៉េចក៏ពូ', r'ពូខ្លាច', r'ពូឯងអាក្រក់', r'ខ្ញុំនឹងខ្លាំងជាង',
    r'ខ្លាចណាស់', r'កុំវាយ', r'អត់ញ៉ាំទេ', r'មិនញ៉ាំទេ', r'តុក្កតា',
    r'ឈឺអត់', r'បើឈឺ', r'ស្ករគ្រាប់', r'ញ៉ាំបាយឱ្យគ្រប់ពេល', r'ឆាប់ធំឡើង', r'ការពារលូកាស',
    r'អាល្អិត', r'ក្មួយ', r'ពូឯងជាឈ្លើង', r'លូកាស\s*ឈឺ', r'ឈឺមែនទេ', r'ពូ\s*ឯង'
]

BUTLER_DIRECT_SPEECH = [
    r'អ្នកនាង\s*កូលីអូន\s*ត្រូវការ',
    r'មិនមែនរកប្តី',
    r'សូមលោកយល់',
    r'ចៅហ្វាយស្រីកំពុង',
    r'សូមកុំប្រកាន់',
    r'ចៅហ្វាយស្រី\s*បេក្ខជន',
    r'សូមគោរព',
    r'រៀបចំរួចរាល់ហើយ'
]

DONNA_DIRECT_SPEECH = [
    r'^ឈ្មោះអ្វី\??$', r'ឈ្មោះអ្វី', r'^សាកមើលទៅ', r'រៀបការជាមួយខ្ញុំ',
    r'ដោះស្រាយការងាររួច', r'សម្លាប់វាចោល',
    r'ចុះមកក្រោម', r'មកនិយាយគ្នា', r'លោកពូកែ', r'លោកមានកូន',
    r'ក្នុងឯកសារថា\s*លោក', r'មូលហេតុ\??', r'លោកឃើញប្រកាស',
    r'ខ្ញុំរើសឪពុកចុង', r'មិនមែនរកគូ', r'អ្វីៗត្រូវបែងចែក',
    r'បន្ទប់គេង', r'ចាស', r'ចា៎'
]

MOTHER_DIRECT_SPEECH = [
    r'ញ៉ាំតែមួយម៉ាត់', r'ប៉ុណ្ណឹងពិបាកណាស់មែនទេ', r'អាឥតប្រយោជន៍',
    r'ដេញចេញពីផ្ទះ', r'ស៊ីញ៉េលែងលះ'
]

NARRATOR_FIRST_PERSON = [
    r'ខ្ញុំ[ស៊ីដើរឃើញឮងក់និយាយទើបមានស្រាប់តែងាកក្រឡេកញោញឹមរើ]',
    r'នាំខ្ញុំ', r'ទ្រូងខ្ញុំ', r'ចង្កាខ្ញុំ', r'ថ្គៀមខ្ញុំ', r'ថ្ពាល់ខ្ញុំ', r'ផ្ទះខ្ញុំ',
    r'ជីវិតខ្ញុំ', r'ខ្លួនខ្ញុំ', r'បាតដៃទោទេ', r'អាពាហ៍ពិពាហ៍នោះ'
]

def analyze_vocal_segment(audio: np.ndarray, sr: int) -> Dict[str, Any]:
    """
    Robust acoustic voice feature extractor using YIN F0 tracking, Spectral Centroid,
    and RMS energy to determine voice gender and speaker characteristics.
    """
    if len(audio) < 512:
        return {"f0": 0.0, "voiced_ratio": 0.0, "centroid": 0.0, "rms": 0.0, "acoustic_gender": "unknown"}
    
    if len(audio.shape) > 1:
        audio = np.mean(audio, axis=1)

    rms = float(np.sqrt(np.mean(audio**2)))
    if rms < 0.006:
        return {"f0": 0.0, "voiced_ratio": 0.0, "centroid": 0.0, "rms": rms, "acoustic_gender": "silence"}

    med_f0 = 0.0
    voiced_ratio = 0.0

    # 1. High-precision YIN pitch estimation via librosa
    try:
        import librosa
        f0_series = librosa.yin(audio, fmin=65, fmax=500, sr=sr)
        valid = f0_series[~np.isnan(f0_series)]
        if len(valid) > 0:
            med_f0 = float(np.median(valid))
            voiced_ratio = len(valid) / len(f0_series)
    except Exception:
        med_f0 = fast_pitch_estimate(audio, sr)
        voiced_ratio = 0.5 if med_f0 > 0 else 0.0

    # 2. Spectral Centroid (timbre brightness)
    avg_sc = 0.0
    try:
        import librosa
        sc = librosa.feature.spectral_centroid(y=audio, sr=sr)
        avg_sc = float(np.mean(sc))
    except Exception:
        pass

    # 3. Classify acoustic gender
    # Young child: F0 >= 270 Hz
    # Adult female: F0 >= 155 Hz, or (F0 >= 142 Hz with bright spectral centroid >= 2500 Hz)
    # Adult male: 0 < F0 < 145 Hz
    if med_f0 >= 270.0:
        acoustic_gender = "child"
    elif med_f0 >= 155.0 or (med_f0 >= 142.0 and avg_sc >= 2500.0):
        acoustic_gender = "female"
    elif 0 < med_f0 < 145.0:
        acoustic_gender = "male"
    else:
        if avg_sc > 3200.0 and rms > 0.02:
            acoustic_gender = "female"
        else:
            acoustic_gender = "unknown"

    return {
        "f0": round(med_f0, 1),
        "voiced_ratio": round(voiced_ratio, 2),
        "centroid": round(avg_sc, 1),
        "rms": round(rms, 4),
        "acoustic_gender": acoustic_gender
    }

def fast_pitch_estimate(audio: np.ndarray, sr: int) -> float:
    """
    Autocorrelation-based F0 pitch estimator fallback.
    """
    if len(audio) < sr * 0.12:
        return 0.0
    s = int(len(audio) * 0.12)
    e = int(len(audio) * 0.88)
    chunk = audio[s:e]
    if len(chunk.shape) > 1:
        chunk = np.mean(chunk, axis=1)
    
    step = max(1, int(sr / 8000))
    sub = chunk[::step]
    sr_sub = sr / step
    
    sub = sub - np.mean(sub)
    if np.max(np.abs(sub)) < 0.012:
        return 0.0
        
    corr = np.correlate(sub, sub, mode='full')
    corr = corr[len(corr)//2:]
    
    min_lag = int(sr_sub / 450)
    max_lag = int(sr_sub / 75)
    
    if max_lag >= len(corr):
        max_lag = len(corr) - 1
    if min_lag >= max_lag:
        return 0.0
        
    peak_lag = min_lag + np.argmax(corr[min_lag:max_lag])
    return float(sr_sub / peak_lag) if peak_lag > 0 else 0.0

def smart_classify_characters(lines: List[Dict[str, Any]], vocals_path: Optional[Path] = None) -> List[Dict[str, Any]]:
    """
    Deep acoustic & linguistic character cast classifier.
    Combines:
    1. Direct acoustic analysis (YIN F0, Spectral Centroid, RMS energy) from vocal track
    2. Dramatic dialogue content analysis (child phrases, butler honorifics, female lead speech)
    3. Explicit subtitle tags as fallback when audio is silent or unvoiced.
    """
    vocal_data = None
    vocal_sr = 44100
    if vocals_path and Path(vocals_path).exists():
        try:
            import soundfile as sf
            vocal_data, vocal_sr = sf.read(str(vocals_path))
            if len(vocal_data.shape) > 1:
                vocal_data = np.mean(vocal_data, axis=1)
        except Exception:
            vocal_data = None

    classified = []
    for item in lines:
        line = dict(item)
        raw = (line.get("raw_text") or "").strip().lower()
        spk_tag = (line.get("speaker") or "").lower().strip()
        text = (line.get("text", "") or line.get("khmer_text", "")).strip()
        en = (line.get("english_text", "") or "").lower().strip()
        s_sec = line.get("start_sec", 0.0)
        e_sec = line.get("end_sec", s_sec + line.get("duration", 2.0))

        # Extract acoustic features if audio is available
        feats = {"f0": 0.0, "voiced_ratio": 0.0, "centroid": 0.0, "rms": 0.0, "acoustic_gender": "unknown"}
        if vocal_data is not None:
            s_idx = max(0, int(s_sec * vocal_sr))
            e_idx = min(len(vocal_data), int(e_sec * vocal_sr))
            if e_idx > s_idx:
                feats = analyze_vocal_segment(vocal_data[s_idx:e_idx], vocal_sr)

        ac_gender = feats["acoustic_gender"]
        f0 = feats["f0"]
        speaker = None

        # Check dialogue content patterns
        is_child_content = any(re.search(pat, text) for pat in CHILD_PATTERNS) or                            any(p in en for p in ["candy", "protect lucas", "grow up fast", "hurt", "uncle", "doll", "teddy"])
        is_lucas_to_child = any(re.search(pat, text) for pat in [r'ឈឺតិចតួចទេ អាល្អិត', r'ឆាប់ធំឡើងណា៎ អាល្អិត'])

        # 1. Child Role:
        if ac_gender == "child":
            speaker = "Child"
        elif is_child_content and not is_lucas_to_child:
            speaker = "Child"

        # 2. Acoustic Voice Analysis (Audio is Ground Truth):
        if not speaker:
            if ac_gender == "female":
                # Adult female voice detected acoustically
                is_mother = any(re.search(pat, text) for pat in MOTHER_DIRECT_SPEECH) or                             any(w in text for w in ["ការសម្តែងរបស់លោក", "លែងលះ", "ឈ្លើង", "គួរឱ្យអាណិត"])
                speaker = "Mother" if is_mother else "Mafia Donna"

            elif ac_gender == "male":
                # Adult male voice detected acoustically
                is_butler = any(re.search(pat, text) for pat in BUTLER_DIRECT_SPEECH) or                             any(p in en for p in ["candidate", "madam", "miss corleone", "housekeeper"])
                speaker = "Butler" if (is_butler or f0 < 88.0) else "Male Lead"

        # 3. Fallback when audio is silent, unvoiced, or not provided:
        if not speaker:
            has_female_tag = any(t in spk_tag for t in FEMALE_TAGS) or any(f"[{t}]" in raw for t in FEMALE_TAGS)
            has_child_tag = any(t in spk_tag for t in CHILD_TAGS) or any(f"[{t}]" in raw for t in CHILD_TAGS)
            has_butler_tag = any(t in spk_tag for t in BUTLER_TAGS) or any(f"[{t}]" in raw for t in BUTLER_TAGS)
            has_mother_tag = any(t in spk_tag for t in ["mother", "ex-wife", "ម្តាយ"]) or any(f"[{t}]" in raw for t in ["mother", "ex-wife"])

            if has_child_tag:
                speaker = "Child"
            elif has_mother_tag:
                speaker = "Mother"
            elif has_female_tag:
                is_mother = any(re.search(pat, text) for pat in MOTHER_DIRECT_SPEECH)
                speaker = "Mother" if is_mother else "Mafia Donna"
            elif has_butler_tag:
                speaker = "Butler"
            elif any(re.search(pat, text) for pat in BUTLER_DIRECT_SPEECH):
                speaker = "Butler"
            elif any(re.search(pat, text) for pat in DONNA_DIRECT_SPEECH):
                speaker = "Mafia Donna"
            elif any(re.search(pat, text) for pat in MOTHER_DIRECT_SPEECH):
                speaker = "Mother"
            else:
                speaker = "Male Lead"

        line["speaker"] = speaker
        preset = CHARACTER_PRESETS.get(speaker, CHARACTER_PRESETS["Male Lead"])
        line["voice"] = preset["voice"]
        line["pitch"] = preset["pitch"]
        line["rate"] = preset["rate"]
        line["volume"] = preset["volume"]
        classified.append(line)

    return classified

def to_seconds(ts: str) -> float:
    ts = ts.strip().replace(",", ".")
    parts = ts.split(":")
    if len(parts) == 3:
        h, m, s = parts
        return int(h) * 3600 + int(m) * 60 + float(s)
    elif len(parts) == 2:
        m, s = parts
        return int(m) * 60 + float(s)
    return float(ts)

def format_timestamp(seconds: float) -> str:
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = seconds % 60
    return f"{h:02d}:{m:02d}:{s:06.3f}".replace(".", ",")

def get_media_info(file_path: Path) -> Dict[str, Any]:
    if not file_path.exists():
        return {}
    cmd = [
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration,size,bit_rate:stream=index,codec_type,codec_name,width,height,r_frame_rate,sample_rate,channels",
        "-of", "json",
        str(file_path)
    ]
    res = subprocess.run(cmd, capture_output=True, text=True, check=True)
    return json.loads(res.stdout)

def get_duration(file_path: Path) -> float:
    cmd = [
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        str(file_path)
    ]
    res = subprocess.run(cmd, capture_output=True, text=True, check=True)
    return float(res.stdout.strip())

def parse_srt(path: Path) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        content = f.read()
    pattern = re.compile(
        r'(\d+)\r?\n(\d{2}:\d{2}:\d{2}[,\.]\d{3})\s*-->\s*(\d{2}:\d{2}:\d{2}[,\.]\d{3})\r?\n(.*?)(?=\r?\n\r?\n\d+|\Z)',
        re.DOTALL
    )
    items = []
    for m in pattern.finditer(content):
        idx, start, end, text = m.groups()
        s_sec = to_seconds(start)
        e_sec = to_seconds(end)
        
        # Check speaker tag [Speaker] or Speaker:
        raw_text = text.strip()
        speaker = "Unknown"
        spk_match = re.match(r'^\[(.*?)\]\s*(.*)', raw_text, re.DOTALL)
        if spk_match:
            speaker = spk_match.group(1).strip()
            clean_text = spk_match.group(2).strip()
        else:
            spk_match2 = re.match(r'^([A-Za-z0-9\s_-]+):\s*(.*)', raw_text, re.DOTALL)
            if spk_match2:
                speaker = spk_match2.group(1).strip()
                clean_text = spk_match2.group(2).strip()
            else:
                clean_text = raw_text

        items.append({
            "idx": int(idx),
            "start": start,
            "end": end,
            "start_sec": s_sec,
            "end_sec": e_sec,
            "duration": round(e_sec - s_sec, 3),
            "speaker": speaker,
            "text": clean_text,
            "raw_text": raw_text
        })
    return items

def export_srt(items: List[Dict[str, Any]], out_path: Path):
    with open(out_path, "w", encoding="utf-8") as f:
        for i, item in enumerate(items, 1):
            s_ts = format_timestamp(item["start_sec"])
            e_ts = format_timestamp(item["end_sec"])
            text = item.get("khmer_text") or item.get("text") or ""
            f.write(f"{i}\n{s_ts} --> {e_ts}\n{text}\n\n")

def separate_stems_demucs(video_or_audio: Path, output_base_dir: Path, progress_cb: Optional[Callable[[str], None]] = None) -> Tuple[Path, Path]:
    """
    Separates vocals and no_vocals using Demucs HTDemucs.
    Returns (vocals_wav, no_vocals_wav).
    """
    stem_dir = output_base_dir / "stems" / video_or_audio.stem
    stem_dir.mkdir(parents=True, exist_ok=True)
    
    no_vocals = stem_dir / "no_vocals.wav"
    vocals = stem_dir / "vocals.wav"

    if no_vocals.exists() and vocals.exists() and no_vocals.stat().st_size > 10000:
        if progress_cb:
            progress_cb(f"Found cached stems in {stem_dir.name}")
        return vocals, no_vocals

    # 1. Extract 44.1kHz stereo WAV
    temp_wav = stem_dir / "source_extracted.wav"
    if progress_cb:
        progress_cb("Extracting audio from source video...")
    cmd_extract = [
        "ffmpeg", "-y", "-i", str(video_or_audio),
        "-vn", "-acodec", "pcm_s16le", "-ar", "44100", "-ac", "2",
        str(temp_wav)
    ]
    subprocess.run(cmd_extract, check=True, capture_output=True)

    # 2. Run Demucs
    if progress_cb:
        progress_cb("Running Demucs AI stem separation (HTDemucs)...")
    cmd_demucs = [
        "demucs", "--two-stems", "vocals",
        "-d", "cpu",
        "-o", str(stem_dir),
        str(temp_wav)
    ]
    subprocess.run(cmd_demucs, check=True)

    # Demucs saves to stem_dir/htdemucs/source_extracted/
    demucs_out = stem_dir / "htdemucs" / "source_extracted"
    if (demucs_out / "no_vocals.wav").exists():
        import shutil
        shutil.move(str(demucs_out / "no_vocals.wav"), str(no_vocals))
        shutil.move(str(demucs_out / "vocals.wav"), str(vocals))

    if progress_cb:
        progress_cb("Stem separation complete.")
    return vocals, no_vocals

async def safe_communicate_tts(text: str, voice: str, rate: str, pitch: str, volume: str, out_path: Path):
    import edge_tts
    out_path.parent.mkdir(parents=True, exist_ok=True)
    
    if out_path.exists() and out_path.stat().st_size > 500:
        return

    for attempt in range(4):
        try:
            if attempt == 0:
                c = edge_tts.Communicate(text=text, voice=voice, rate=rate, pitch=pitch, volume=volume)
            elif attempt == 1:
                c = edge_tts.Communicate(text=text, voice=voice, rate=rate, pitch="+0Hz", volume=volume)
            else:
                c = edge_tts.Communicate(text=text, voice=voice)
            await c.save(str(out_path))
            if out_path.exists() and out_path.stat().st_size > 500:
                return
        except Exception:
            if attempt == 3:
                raise
            await asyncio.sleep(0.5 * (attempt + 1))

def process_single_line_audio(raw_mp3: Path, adj_wav: Path, target_dur: float, max_allowed: float) -> float:
    """
    Applies highpass, clarity EQ, and precise atempo stretch so dialogue fits the scene slot.
    """
    raw_dur = get_duration(raw_mp3)
    speed_factor = 1.0

    if raw_dur > max_allowed:
        speed_factor = raw_dur / (max_allowed * 0.96)
    elif raw_dur > target_dur * 1.25 and (raw_dur - target_dur) > 0.4:
        speed_factor = raw_dur / (target_dur * 1.15)

    speed_factor = max(0.85, min(1.40, speed_factor))

    # Vocal EQ & time stretch
    filter_chain = f"highpass=f=80,equalizer=f=3200:t=q:w=1.2:g=2.2,atempo={speed_factor:.4f}"
    cmd = [
        "ffmpeg", "-y", "-i", str(raw_mp3),
        "-af", filter_chain,
        "-ar", "44100", "-ac", "2",
        str(adj_wav)
    ]
    subprocess.run(cmd, check=True, capture_output=True)
    return get_duration(adj_wav)

async def synthesize_dialogue_timeline(
    items: List[Dict[str, Any]],
    character_map: Dict[str, Dict[str, str]],
    temp_dir: Path,
    progress_cb: Optional[Callable[[str, float], None]] = None
) -> List[Dict[str, Any]]:
    """
    Synthesizes every subtitle line into Khmer audio with matched emotion and timing.
    """
    temp_dir.mkdir(parents=True, exist_ok=True)
    results = []
    total = len(items)

    for i, item in enumerate(items):
        idx = item["idx"]
        s_sec = item["start_sec"]
        e_sec = item["end_sec"]
        target_dur = e_sec - s_sec

        next_s_sec = items[i + 1]["start_sec"] if i + 1 < total else s_sec + target_dur + 3.0
        max_allowed = max(target_dur, next_s_sec - s_sec - 0.12)

        # Match speaker and prosody
        speaker = item.get("speaker", "Male Lead")
        cfg = character_map.get(speaker) or CHARACTER_PRESETS.get(speaker) or CHARACTER_PRESETS["Male Lead"]
        
        voice = item.get("voice") or cfg.get("voice", "km-KH-PisethNeural")
        rate = item.get("rate") or cfg.get("rate", "+0%")
        pitch = item.get("pitch") or cfg.get("pitch", "+0Hz")
        volume = item.get("volume") or cfg.get("volume", "+0%")

        km_text = (item.get("khmer_text") or item.get("text") or "").strip()
        if not km_text:
            continue

        import hashlib
        content_sig = f"{km_text}|{voice}|{rate}|{pitch}|{volume}"
        sig_hash = hashlib.md5(content_sig.encode("utf-8")).hexdigest()[:8]

        raw_path = temp_dir / f"line_{idx:03d}_{sig_hash}_raw.mp3"
        adj_path = temp_dir / f"line_{idx:03d}_{sig_hash}_adj.wav"

        await safe_communicate_tts(km_text, voice, rate, pitch, volume, raw_path)
        final_dur = process_single_line_audio(raw_path, adj_path, target_dur, max_allowed)

        if progress_cb:
            pct = (i + 1) / total
            progress_cb(f"Synthesizing #{idx:02d} [{speaker}]: {km_text[:30]}...", pct)

        results.append({
            "idx": idx,
            "start": s_sec,
            "end": s_sec + final_dur,
            "duration": final_dur,
            "wav_path": adj_path,
            "speaker": speaker,
            "text": km_text
        })

    return results

def assemble_master_speech_buffer(dub_items: List[Dict[str, Any]], total_duration: float, output_path: Path):
    """
    Assembles all dialogue items into a continuous, sample-accurate stereo 44.1kHz master audio buffer.
    """
    sample_rate = 44100
    channels = 2
    total_samples = int(total_duration * sample_rate) + sample_rate * 2
    master_audio = np.zeros((total_samples, channels), dtype=np.float32)

    for item in dub_items:
        s_sample = int(item["start"] * sample_rate)
        with wave.open(str(item["wav_path"]), "rb") as wf:
            n_frames = wf.getnframes()
            data = wf.readframes(n_frames)
            s_width = wf.getsampwidth()
            n_ch = wf.getnchannels()

            if s_width == 2:
                samples = np.frombuffer(data, dtype=np.int16).astype(np.float32) / 32768.0
            else:
                samples = np.frombuffer(data, dtype=np.float32)

            if n_ch == 1:
                samples = np.column_stack([samples, samples])
            else:
                samples = samples.reshape(-1, 2)

        e_sample = s_sample + len(samples)
        if e_sample > len(master_audio):
            pad = e_sample - len(master_audio)
            master_audio = np.pad(master_audio, ((0, pad), (0, 0)))

        master_audio[s_sample:e_sample] += samples

    # Normalization to -1.5 dB peak
    max_peak = np.max(np.abs(master_audio))
    if max_peak > 0:
        target = 0.84
        if max_peak > target:
            master_audio = master_audio * (target / max_peak)

    master_int16 = (master_audio * 32767.0).clip(-32768, 32767).astype(np.int16)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(output_path), "wb") as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(master_int16.tobytes())

def mix_stems_and_mux_video(
    video_in: Path,
    bgm_wav: Path,
    speech_wav: Path,
    video_out: Path,
    voice_boost: float = 2.0,
    bgm_volume: float = 0.22,
    duck_ratio: float = 6.0,
    duck_attack: int = 15,
    duck_release: int = 250,
    limiter_peak: float = 0.95,
    progress_cb: Optional[Callable[[str], None]] = None
):
    """
    Mixes speech and BGM using proper asplit sidechain ducking and remuxes with source video stream.
    Produces clean Khmer Dubbed video output.
    """
    mixed_wav = video_out.parent / "temp_mixed.wav"

    if progress_cb:
        progress_cb("Mixing vocal bus with ducked BGM using dynamic sidechain...")

    # Robust FFmpeg sidechain filter with asplit:
    # 1. Speech is split into [speech_sc] (sidechain control) and [speech_mix] (audible output).
    # 2. BGM is sidechain compressed by [speech_sc], then scaled to bgm_volume.
    # 3. [bgm_bed] and [speech_mix] are summed with normalize=0 and mastered through a brickwall limiter.
    duck_ratio = max(1.0, min(100.0, float(duck_ratio)))
    filter_complex = (
        f"[1:a]volume={voice_boost:.2f},alimiter=limit={limiter_peak-0.03:.2f}:attack=5:release=50,asplit=2[speech_sc][speech_mix];"
        f"[0:a][speech_sc]sidechaincompress=threshold=0.02:ratio={duck_ratio:.1f}:attack={duck_attack}:release={duck_release}[ducked_bgm];"
        f"[ducked_bgm]volume={bgm_volume:.2f}[bgm_bed];"
        f"[bgm_bed][speech_mix]amix=inputs=2:duration=longest:dropout_transition=2:normalize=0,alimiter=limit={limiter_peak:.2f}:attack=5:release=50[outa]"
    )

    cmd_mix = [
        "ffmpeg", "-y",
        "-i", str(bgm_wav),
        "-i", str(speech_wav),
        "-filter_complex", filter_complex,
        "-map", "[outa]",
        "-ar", "44100", "-ac", "2",
        str(mixed_wav)
    ]
    subprocess.run(cmd_mix, check=True, capture_output=True)

    # Multiplex with video without re-encoding video stream
    if progress_cb:
        progress_cb(f"Muxing lossless video track into: {video_out.name}...")

    cmd_mux = [
        "ffmpeg", "-y",
        "-i", str(video_in),
        "-i", str(mixed_wav),
        "-c:v", "copy",
        "-c:a", "aac", "-b:a", "192k",
        "-map", "0:v:0",
        "-map", "1:a:0",
        "-shortest",
        str(video_out)
    ]
    subprocess.run(cmd_mux, check=True, capture_output=True)

    # Clean up temp mixed wav
    if mixed_wav.exists():
        mixed_wav.unlink(missing_ok=True)

    if progress_cb:
        progress_cb("Dubbing and multiplexing complete!")

def discover_dramas(root_dir: Path, completed_dir: Optional[Path] = None) -> List[Dict[str, Any]]:
    """
    Scans drama downloads directory to discover all drama series, episodes, and subtitle pairs.
    Also checks completed_dir for existing finalized dubbed outputs.
    """
    results = []
    if not root_dir.exists():
        return results

    for item in root_dir.iterdir():
        if item.is_dir():
            if item.name.lower() in ["completed", "stems", "studio_cache", "uploads", "static"]:
                continue
            # Check for mp4 files
            vids = sorted(list(item.glob("*.mp4")))
            for v in vids:
                # Find matching SRTs
                base_stem = v.stem
                en_srts = list(item.glob(f"{base_stem}*.srt"))
                # Filter out _km or _subtitles_edit for original
                orig_srt = None
                km_srt = None
                for s in en_srts:
                    if "_km" in s.name or "_subtitles_edit" in s.name:
                        km_srt = s
                    else:
                        orig_srt = s
                
                # Check for txt fallback
                km_txt = None
                m = re.search(r'(?:ep|ep_)?(\d+)', v.name, re.IGNORECASE)
                ep_num = int(m.group(1)) if m else None
                if ep_num is not None:
                    txt_candidates = list(item.glob(f"*ep*{ep_num}*km*.txt"))
                    if txt_candidates:
                        km_txt = txt_candidates[0]

                # Check completed dubbed video
                has_dubbed = False
                dubbed_path = None
                if completed_dir and completed_dir.exists():
                    cand1 = completed_dir / f"{v.stem}_Khmer_Dubbed.mp4"
                    cand2 = completed_dir / f"{v.name}"
                    if cand1.exists():
                        has_dubbed = True
                        dubbed_path = cand1
                    elif cand2.exists():
                        has_dubbed = True
                        dubbed_path = cand2
                    elif v.name == "EP01.mp4" and (completed_dir / "EP01_Khmer_Dubbed.mp4").exists():
                        has_dubbed = True
                        dubbed_path = completed_dir / "EP01_Khmer_Dubbed.mp4"
                    elif ep_num is not None:
                        ep_candidates = list(completed_dir.glob(f"*ep*{ep_num}*Khmer_Dubbed.mp4")) + \
                                        list(completed_dir.glob(f"*Ep_{ep_num:02d}*Khmer_Dubbed.mp4"))
                        if ep_candidates:
                            has_dubbed = True
                            dubbed_path = ep_candidates[0]

                results.append({
                    "series": item.name,
                    "title": v.name,
                    "video_path": v,
                    "en_srt": orig_srt,
                    "km_srt": km_srt,
                    "km_txt": km_txt,
                    "has_dubbed": has_dubbed,
                    "dubbed_path": dubbed_path
                })
        elif item.suffix.lower() == ".mp4":
            has_dubbed = False
            dubbed_path = None
            if completed_dir and completed_dir.exists():
                cand = completed_dir / f"{item.stem}_Khmer_Dubbed.mp4"
                if cand.exists():
                    has_dubbed = True
                    dubbed_path = cand
                elif item.name == "EP01.mp4" and (completed_dir / "EP01_Khmer_Dubbed.mp4").exists():
                    has_dubbed = True
                    dubbed_path = completed_dir / "EP01_Khmer_Dubbed.mp4"

            results.append({
                "series": "Root",
                "title": item.name,
                "video_path": item,
                "en_srt": None,
                "km_srt": None,
                "km_txt": None,
                "has_dubbed": has_dubbed,
                "dubbed_path": dubbed_path
            })
    return results
