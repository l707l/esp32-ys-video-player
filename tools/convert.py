#!/usr/bin/env python3
"""
ESP32 YS Video Converter — Optimized MJPEG for Cheap Yellow Display

Converts any video (MP4, AVI, MKV, MOV, WebM) to MJPEG format
optimized for the ESP32-2432S028 (ILI9341 240x320).

Usage:
    python3 convert.py input.mp4                    # single file
    python3 convert.py input.mp4 output.mjpeg      # custom output
    python3 convert.py input/                      # entire folder
    python3 convert.py input.mp4 --quality high   # quality preset
    python3 convert.py input.mp4 -r 20             # custom FPS
    python3 convert.py input.mp4 --batch            # batch mode
    python3 convert.py --scan /path/to/sd/card     # scan SD card

Quality presets:
    low    : 240x320, 15fps, qscale 8  (~400KB/min)
    medium : 240x320, 20fps, qscale 5  (~800KB/min)
    high   : 240x320, 25fps, qscale 3  (~1.2MB/min)
    ultra  : 240x320, 30fps, qscale 2  (~1.8MB/min)

Author: L707L
"""

import sys
import os
import subprocess
import argparse
import json
import re
import shutil
from pathlib import Path

# ═══════════════════════════════════════════════════════════
# CONFIGURATION
# ═══════════════════════════════════════════════════════════
TARGET_W = 240
TARGET_H = 320
FPS_PRESETS = {"low": 15, "medium": 20, "high": 25, "ultra": 30}
QSCALE_MAP = {"low": 8, "medium": 5, "high": 3, "ultra": 2}
DEFAULT_QUALITY = "high"
SD_MJPEG_DIR = "/mjpeg"

# ═══════════════════════════════════════════════════════════
# UTILITIES
# ═══════════════════════════════════════════════════════════

def run(cmd, capture=True, timeout=300):
    """Run command with optional capture and timeout."""
    try:
        if capture:
            result = subprocess.run(
                cmd, shell=True, capture_output=True,
                text=True, timeout=timeout
            )
            return result.stdout, result.stderr, result.returncode
        else:
            ret = subprocess.run(cmd, shell=True, timeout=timeout)
            return "", "", ret.returncode
    except subprocess.TimeoutExpired:
        return "", "TIMEOUT", -1

def get_video_info(path):
    """Get video dimensions, duration, fps using ffprobe."""
    cmd = (
        f'ffprobe -v quiet -print_format json '
        f'-show_streams -show_format "{path}"'
    )
    out, err, rc = run(cmd)
    if rc != 0:
        return None
    try:
        data = json.loads(out)
        streams = data.get("streams", [])
        fmt = data.get("format", {})

        video_stream = None
        for s in streams:
            if s.get("codec_type") == "video":
                video_stream = s
                break

        if not video_stream:
            return None

        vs = video_stream

        fps_str = vs.get("r_frame_rate", "25/1")
        if "/" in fps_str:
            num, den = fps_str.split("/")
            fps = float(num) / float(den)
        else:
            fps = float(fps_str)

        # Duration: try format first, then estimate from fps+frames
        duration = float(fmt.get("duration", 0))
        if duration <= 0:
            # MJPEG often doesn't expose duration — estimate from fps
            nb_frames = vs.get("nb_frames", "")
            if nb_frames and nb_frames.isdigit():
                duration = int(nb_frames) / fps if fps > 0 else 0
            else:
                duration = 0  # unknown — converter will skip

        return {
            "width": vs.get("width", 0),
            "height": vs.get("height", 0),
            "duration": duration,
            "fps": fps,
            "bitrate": int(fmt.get("bit_rate", 0)),
            "size": int(fmt.get("size", 0)),
            "codec": vs.get("codec_name", "unknown")
        }
    except Exception as e:
        print(f"  [ERROR] ffprobe parse: {e}")
        return None

def format_size(bytes):
    if bytes < 1024:
        return f"{bytes}B"
    elif bytes < 1024 * 1024:
        return f"{bytes/1024:.1f}KB"
    else:
        return f"{bytes/1024/1024:.1f}MB"

def format_time(seconds):
    m = int(seconds // 60)
    s = int(seconds % 60)
    return f"{m:02d}:{s:02d}"

def hms_timestamp():
    from datetime import datetime
    return datetime.now().strftime("%H:%M:%S")

def print_info(msg):
    print(f"  [INFO] {msg}")

def print_warn(msg):
    print(f"  [WARN] {msg}")

def print_error(msg):
    print(f"  [ERROR] {msg}")

def print_success(msg):
    print(f"  [OK] {msg}")

def print_header(msg):
    print(f"\n{'='*60}")
    print(f"  {msg}")
    print(f"{'='*60}")

# ═══════════════════════════════════════════════════════════
# CORE CONVERSION — FFmpeg MJPEG
# ═══════════════════════════════════════════════════════════

def convert_video(input_path, output_path, quality="high",
                  fps=None, width=TARGET_W, height=TARGET_H,
                  deinterlace=True, verbose=False):
    """
    Convert video to MJPEG optimized for ESP32 ILI9341 display.

    Args:
        input_path   : Source video file
        output_path  : Destination .mjpeg file
        quality      : low/medium/high/ultra
        fps          : Override FPS (None = use preset)
        width/height : Target resolution
        deinterlace  : Apply yadif deinterlace for interlaced sources

    Returns:
        dict with stats or None on failure
    """

    if not os.path.exists(input_path):
        print_error(f"File not found: {input_path}")
        return None

    qscale = QSCALE_MAP.get(quality, QSCALE_MAP[DEFAULT_QUALITY])
    target_fps = fps or FPS_PRESETS.get(quality, FPS_PRESETS[DEFAULT_QUALITY])

    # Input analysis
    info = get_video_info(input_path)
    if not info:
        print_error(f"Cannot read video info: {input_path}")
        return None

    is_mjpeg_input = (info['codec'] == 'mjpeg')

    print_info(f"Source: {info['width']}x{info['height']} {info['fps']:.1f}fps "
               f"{'N/A' if info['duration'] == 0 else format_time(info['duration'])} {info['codec']}")

    if is_mjpeg_input:
        print_info("MJPEG source detected — re-encoding for ESP32 compatibility")

    # Calculate letterbox to maintain aspect ratio
    src_w, src_h = info['width'], info['height']
    aspect = src_w / src_h if src_h > 0 else 16/9
    target_aspect = width / height  # 0.75 for 240/320

    if abs(aspect - target_aspect) > 0.01:
        # Need letterbox — calculate padding
        if aspect > target_aspect:
            # Video is wider — pad top/bottom
            pad_h = int(src_w / target_aspect)
            pad_top = (pad_h - src_h) // 2
            pad_bottom = pad_h - src_h - pad_top
            vf_filter = f"scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height},pad={width}:{height}:0:{pad_top},setsar=1"
        else:
            # Video is taller — pad left/right
            pad_w = int(src_h * target_aspect)
            pad_left = (pad_w - src_w) // 2
            pad_right = pad_w - src_w - pad_left
            vf_filter = f"scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height},pad={width}:{height}:{pad_left}:0,setsar=1"
    else:
        # Perfect match — just scale
        vf_filter = f"scale={width}:{height}:force_original_aspect_ratio=decrease,setsar=1"

    if deinterlace:
        vf_filter = "yadif," + vf_filter

    # Estimate output size
    est_size_mb = (info['duration'] * target_fps * width * height * qscale) / (1024 * 1024 * 1000)
    est_size = int(est_size_mb * 1024 * 1024)

    print_info(f"Target: {width}x{height} {target_fps}fps qscale={qscale} "
               f"→ est. {format_size(est_size)}")

    # Build ffmpeg command
    # Key optimizations:
    # - codec:v mjpeg: MotionJPEG (native ESP32 decoder support)
    # - qscale:v {qscale}: quality (2=best, 31=worst)
    # - sequential encoding: no B-frames (ESP32 can't decode them efficiently)
    # - huffman: optimal (lossless JPEG table encoding)
    # - g 1: all frames are keyframes (instant seek, no GOP latency)
    # - vsync cfr: constant frame rate for predictable timing
    # - global_header: embedded in every frame for standalone decoding

    cmd = (
        f'ffmpeg -y -v quiet '
        f'-i "{input_path}" '
        f'-c:v mjpeg '
        f'-qscale:v {qscale} '
        f'-vf "{vf_filter}" '
        f'-r {target_fps} '
        f'-vsync cfr '
        f'-g 1 '
        f'-pix_fmt rgb565le '
        f'-f mjpeg '
        f'"{output_path}"'
    )

    if verbose:
        print(f"\n  ffmpeg: {cmd}\n")

    print_info(f"Encoding {format_time(info['duration']) if info['duration'] > 0 else 'N/A'} video...")
    print_info("This may take a while for long videos...")

    # Progress tracking
    start_time = subprocess.time.time()
    proc = subprocess.Popen(cmd, shell=True, stderr=subprocess.PIPE, stdout=subprocess.PIPE)

    total_duration = info['duration'] if info['duration'] > 0 else 60  # fallback
    last_pct = -1
    has_progress = (info['duration'] > 0)

    # Poll for progress
    while True:
        line = proc.stderr.readline()
        if not line and proc.poll() is not None:
            break
        # Only show progress bar if we know the total duration
        if not has_progress:
            continue
        # Parse time= in ffmpeg output
        line_str = line.decode('utf-8', errors='ignore') if isinstance(line, bytes) else str(line)
        if 'time=' in line_str:
            match = re.search(r'time=(\d+):(\d+):(\d+\.\d+)', line_str)
            if match:
                h, m, s = int(match.group(1)), int(match.group(2)), float(match.group(3))
                elapsed = h*3600 + m*60 + s
                pct = min(100, int(elapsed / total_duration * 100))
                if pct != last_pct:
                    bar = "█" * (pct // 5) + "░" * (20 - pct // 5)
                    elapsed_str = format_time(elapsed)
                    print(f"\r  [{bar}] {pct:3d}%  {elapsed_str}/{format_time(total_duration)}   ", end="", flush=True)
                    last_pct = pct

    proc.wait()
    elapsed_total = subprocess.time.time() - start_time

    print()  # newline after progress bar

    if proc.returncode != 0:
        stderr = proc.stderr.read().decode() if proc.stderr else ""
        print_error(f"ffmpeg failed: {stderr[:500]}")
        return None

    if not os.path.exists(output_path):
        print_error(f"Output file not created: {output_path}")
        return None

    # Get actual output stats from the file (MJPEG may have different frame count after re-encode)
    out_info = get_video_info(output_path)
    output_size = os.path.getsize(output_path)
    frames_out = int(out_info['fps'] * out_info['duration']) if out_info and out_info['duration'] > 0 else 0
    real_duration = out_info['duration'] if out_info and out_info['duration'] > 0 else elapsed_total
    compression_ratio = (info['size'] / output_size) if output_size > 0 else 0
    encode_fps = frames_out / elapsed_total if elapsed_total > 0 and frames_out > 0 else 0

    result = {
        "input": input_path,
        "output": output_path,
        "quality": quality,
        "target_fps": target_fps,
        "width": width,
        "height": height,
        "qscale": qscale,
        "duration": real_duration,
        "input_size": info['size'],
        "output_size": output_size,
        "compression_ratio": round(compression_ratio, 1),
        "encode_time": round(elapsed_total, 1),
        "encode_fps": round(encode_fps, 1) if encode_fps > 0 else round(real_duration / elapsed_total, 1) if elapsed_total > 0 else 0
    }

    print_success(f"Done! {format_size(output_size)} "
                  f"({result['compression_ratio']:.1f}x {'smaller' if compression_ratio > 1 else 'larger'}) "
                  f"in {format_time(elapsed_total)} "
                  f"({result['encode_fps']:.1f}x realtime)")

    return result

# ═══════════════════════════════════════════════════════════
# BATCH PROCESSING
# ═══════════════════════════════════════════════════════════

def batch_convert(input_dir, output_dir=None, quality="high",
                  fps=None, scan_subdirs=False):
    """
    Convert all videos in a directory.
    Recursively scans for MP4, AVI, MKV, MOV, WebM, FLV, WMV.
    """

    extensions = {".mp4", ".avi", ".mkv", ".mov", ".webm", ".flv", ".wmv", ".m4v"}
    if output_dir is None:
        output_dir = input_dir

    if not os.path.exists(input_dir):
        print_error(f"Directory not found: {input_dir}")
        return []

    print_header(f"BATCH CONVERT — {input_dir}")
    print_info(f"Quality: {quality} | FPS: {fps or 'auto'} | Recursive: {scan_subdirs}")
    print_info(f"Output: {output_dir}")

    videos = []
    if os.path.isfile(input_dir):
        videos = [input_dir]
    else:
        for root, dirs, files in os.walk(input_dir):
            for f in files:
                if Path(f).suffix.lower() in extensions:
                    videos.append(os.path.join(root, f))
            if not scan_subdirs:
                dirs.clear()  # don't recurse

    if not videos:
        print_warn("No video files found")
        return []

    print_info(f"Found {len(videos)} video(s)")

    results = []
    for i, video_path in enumerate(videos, 1):
        print_header(f"[{i}/{len(videos)}] {os.path.basename(video_path)}")

        input_name = os.path.splitext(os.path.basename(video_path))[0]
        output_name = input_name + ".mjpeg"
        output_path = os.path.join(output_dir, output_name)

        result = convert_video(
            video_path, output_path,
            quality=quality, fps=fps,
            width=TARGET_W, height=TARGET_H,
            deinterlace=True, verbose=False
        )

        if result:
            results.append(result)

    # Summary
    print_header("BATCH COMPLETE")
    total_input = sum(r['input_size'] for r in results)
    total_output = sum(r['output_size'] for r in results)
    total_time = sum(r['encode_time'] for r in results)
    total_dur = sum(r['duration'] for r in results)

    print_info(f"Files processed: {len(results)}/{len(videos)}")
    print_info(f"Total input:  {format_size(total_input)}")
    print_info(f"Total output: {format_size(total_output)} "
               f"({total_input/total_output:.1f}x compression)")
    print_info(f"Total time: {format_time(total_time)} "
               f"({total_dur/total_time:.1f}x realtime)")

    return results

# ═══════════════════════════════════════════════════════════
# SD CARD SCANNER — shows what's on the card
# ═══════════════════════════════════════════════════════════

def scan_sd_card(path):
    """List all .mjpeg files on an SD card (or mounted path)."""
    if not os.path.exists(path):
        print_error(f"Path not found: {path}")
        return

    print_header(f"SD CARD CONTENTS — {path}")

    mjpegs = []
    for root, dirs, files in os.walk(path):
        for f in files:
            if f.endswith('.mjpeg'):
                full = os.path.join(root, f)
                size = os.path.getsize(full)
                mjpegs.append((full, size))

    if not mjpegs:
        print_warn("No .mjpeg files found")
        return

    total = sum(s for _, s in mjpegs)
    print_info(f"{len(mjpegs)} video(s) — {format_size(total)} total")

    for p, size in sorted(mjpegs, key=lambda x: x[1], reverse=True):
        print(f"  {format_size(size):>10}  {p}")

    print()
    print_info("Copy files to /mjpeg/ on your SD card")
    print_info("Insert SD card and power on the ESP32")

# ═══════════════════════════════════════════════════════════
# ANALYZE MJPEG QUALITY — verify converted file
# ═══════════════════════════════════════════════════════════

def analyze_mjpeg(path):
    """Analyze a converted MJPEG — frame count, fps, quality."""
    if not os.path.exists(path):
        print_error(f"File not found: {path}")
        return

    info = get_video_info(path)
    if not info:
        print_error(f"Cannot read: {path}")
        return

    size = os.path.getsize(path)
    print_header(f"MJPEG ANALYSIS — {os.path.basename(path)}")
    print_info(f"Resolution: {info['width']}x{info['height']}")
    print_info(f"Duration:  {format_time(info['duration'])}")
    print_info(f"FPS:      {info['fps']:.1f}")
    print_info(f"Size:     {format_size(size)}")
    print_info(f"Codec:    {info['codec']}")

    bps = (size * 8) / info['duration'] if info['duration'] > 0 else 0
    kbps = bps / 1000
    print_info(f"Bitrate:  {kbps:.0f} kbps")

    # Estimated quality metric
    kbps_per_pixel = kbps / (info['width'] * info['height'])
    if kbps_per_pixel < 0.05:
        quality_label = "LOW (may be blocky)"
    elif kbps_per_pixel < 0.15:
        quality_label = "MEDIUM (acceptable)"
    elif kbps_per_pixel < 0.3:
        quality_label = "HIGH (good quality)"
    else:
        quality_label = "ULTRA (excellent)"
    print_info(f"Quality:  {quality_label} ({kbps_per_pixel:.3f} kbps/pixel)")

    if info['width'] != TARGET_W or info['height'] != TARGET_H:
        print_warn(f"Resolution is {info['width']}x{info['height']} "
                   f"(expected {TARGET_W}x{TARGET_H})")

    return info

# ═══════════════════════════════════════════════════════════
# CLI INTERFACE
# ═══════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description="ESP32 YS Video Converter — MJPEG for Cheap Yellow Display",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s video.mp4                    # Convert single file
  %(prog)s video.mp4 -q ultra           # Best quality
  %(prog)s video.mp4 -r 20              # 20 fps
  %(prog)s folder/ --batch              # Batch convert
  %(prog)s video.mp4 -o output.mjpeg    # Custom output name
  %(prog)s --scan /Volumes/SD card      # Scan SD card
  %(prog)s video.mjpeg --analyze        # Analyze converted file
        """
    )

    parser.add_argument("input", nargs="?", help="Input video file or folder")
    parser.add_argument("-o", "--output", help="Output file (default: input.mjpeg)")
    parser.add_argument("-q", "--quality", choices=["low", "medium", "high", "ultra"],
                        default="high", help="Quality preset (default: high)")
    parser.add_argument("-r", "--fps", type=int, help="Frame rate override (default: auto)")
    parser.add_argument("-b", "--batch", action="store_true", help="Batch mode")
    parser.add_argument("--scan", metavar="PATH", help="Scan SD card at PATH")
    parser.add_argument("--analyze", metavar="FILE", help="Analyze MJPEG file")
    parser.add_argument("-v", "--verbose", action="store_true", help="Show ffmpeg command")
    parser.add_argument("--no-deinterlace", action="store_true", help="Skip deinterlace")

    args = parser.parse_args()

    print_header("ESP32 YS Video Converter v1.0")
    print_info(f"Target: {TARGET_W}x{TARGET_H} | Quality: {args.quality} | FPS: {args.fps or 'auto'}")

    # Check ffmpeg
    _, stderr, rc = run("ffmpeg -version")
    if rc != 0:
        print_error("ffmpeg not found! Install: brew install ffmpeg (macOS) or apt install ffmpeg (Linux)")
        sys.exit(1)
    print_success("ffmpeg found")

    if args.scan:
        scan_sd_card(args.scan)
        sys.exit(0)

    if args.analyze:
        analyze_mjpeg(args.analyze)
        sys.exit(0)

    if not args.input:
        parser.print_help()
        sys.exit(0)

    # Determine input type and output
    if os.path.isdir(args.input) or args.batch:
        batch_convert(args.input, quality=args.quality, fps=args.fps)
    else:
        if args.output:
            output_path = args.output
        else:
            base = os.path.splitext(args.input)[0]
            output_path = base + ".mjpeg"

        convert_video(
            args.input, output_path,
            quality=args.quality, fps=args.fps,
            deinterlace=not args.no_deinterlace,
            verbose=args.verbose
        )

if __name__ == "__main__":
    main()