# ESP32 YS Video Player — Cheap Yellow Display (CYD) Optimized

> High-performance MJPEG video player for ESP32-2432S028 (ILI9341 240x320)
> Upgrade of [thelastoutpostworkshop/esp32-2432S028_video_player](https://github.com/thelastoutpostworkshop/esp32-2432S028_video_player)
>
> **Author:** L707L | **License:** MIT

---

## Hardware

**Cheap Yellow Display (CYD) ESP32-2432S028**
- ESP32 dual-core 240MHz
- ILI9341 display 240x320 SPI (80MHz)
- SD card slot (VSPI)
- USB-C power
- Single GPIO button (BOOT/IO0)

---

## Quick Start

### 1. Convert Your Videos

```bash
# Install ffmpeg (macOS)
brew install ffmpeg

# Linux: sudo apt install ffmpeg

# Single file — high quality (25fps)
python3 tools/convert.py video.mp4

# Batch folder
python3 tools/convert.py videos_folder/ --batch

# Ultra quality (30fps)
python3 tools/convert.py video.mp4 -q ultra

# Custom FPS
python3 tools/convert.py video.mp4 -r 20

# Scan SD card
python3 tools/convert.py --scan /Volumes/SD

# Analyze converted file
python3 tools/convert.py --analyze output.mjpeg
```

**Quality presets:**

| Preset | FPS | QScale | Est. size |
|--------|-----|--------|-----------|
| low | 15 | 8 | ~400KB/min |
| medium | 20 | 5 | ~800KB/min |
| high | 25 | 3 | ~1.2MB/min |
| ultra | 30 | 2 | ~1.8MB/min |

### 2. Copy to SD Card

```
SD card/
└── mjpeg/
    ├── video1.mjpeg
    ├── video2.mjpeg
    └── video3.mjpeg
```

### 3. Flash Firmware

```bash
# Install ESP-IDF
./install.sh

# Build
idf.py build

# Flash (hold BOOT button during upload)
idf.py flash
```

### 4. Connect

Power on — auto-plays immediately. No menus.

---

## Controls — Single Button (GPIO0)

| Action | Result |
|--------|--------|
| 1 click | Pause / Resume |
| 2 clicks | Next video |
| 3 clicks | Previous video |
| Hold | (reserved) |

Button debounce: 50ms minimum gap, 400ms max window.

---

## Architecture

```
esp32-ys-video-player/
├── main/
│   └── main.c          # ESP-IDF app (SPI DMA, JPEG decoder, button ISR)
├── components/
│   ├── ili9341/        # Display driver component
│   ├── jpeg_dec/       # JPEG decoder component (wrapper)
│   ├── button/         # Multi-click button handler
│   └── sdcard/         # SD card + FATFS component
├── tools/
│   └── convert.py      # Python converter (ffmpeg backend)
├── sdkconfig.defaults  # ESP-IDF config
└── README.md
```

---

## Firmware — Key Optimizations

### vs. Original (Arduino-based)

| Feature | Original | This version |
|---------|----------|-------------|
| Platform | Arduino framework | ESP-IDF native |
| SPI speed | 80MHz fixed | 80MHz + DMA double-buffer |
| JPEG decoder | JPEGDEC (Arduino lib) | Integrated esp_jpeg |
| Button | Simple digitalRead | Hardware ISR + state machine |
| Memory | heap_caps_malloc | DMA-capable aligned buffers |
| Frame timing | millis() polling | esp_timer for precise FPS |
| Buffer strategy | Read-ahead 1/5 | Adaptive based on free heap |

### Memory Layout

```
IRAM:   Button ISR, SPI transactions, hot paths
DRAM:   Frame buffer (240x320x2 = 153KB)
DMA:    SPI transfer buffer (4KB chunks)
PSRAM:  (not used — CYD has no PSRAM)
```

### Display Pipeline

```
SD Card (SPI) → JPEG buffer → esp_jpeg decode → RGB565 → SPI DMA → ILI9341
                  ~80KB              ~150KB           153KB      80MHz
```

---

## Converter — Technical Details

The converter produces **sequential MJPEG** — every frame is a complete JPEG
keyframe. No H.264/H.265, no inter-frame compression.

**Why sequential MJPEG for ESP32:**
- No GOP (group of pictures) — no decoder buffer needed for reference frames
- Every frame is independently decodable (instant seek, no latency)
- JPEGDEC handles baseline JPEG natively in hardware
- No B-frames = predictable decode time per frame
- Perfect for cyclic playback with no audio

**FFmpeg pipeline:**

```
Input → yadif (deinterlace) → scale+padsar → mjpeg qscale N
     → sequential output (g=1, vsync cfr, rgb565le)
```

**FFmpeg quality vs. size tradeoffs:**

| QScale | Quality | Notes |
|--------|---------|-------|
| 2 | Ultra | Near-lossless, large files |
| 3 | High | Recommended (0.04 kbps/px) |
| 5 | Medium | Good for long videos |
| 8+ | Low | Only if storage limited |

---

## Building From Source

### Prerequisites

```bash
# ESP-IDF 5.x
git clone https://github.com/espressif/esp-idf.git ~/esp/esp-idf
cd ~/esp/esp-idf
./install.sh
. ./export.sh

# ffmpeg (for converter)
brew install ffmpeg    # macOS
sudo apt install ffmpeg # Linux
```

### Build & Flash

```bash
cd esp32-ys-video-player
. ~/esp/esp-idf/export.sh

idf.py build
idf.py flash -p /dev/ttyUSB0 monitor
```

---

## Troubleshooting

**Display shows nothing:**
- Check BL_PIN — some CYD models use GPIO27 for backlight
- Try reducing SPI speed to 40MHz in `main.c`

**Video stutters or drops frames:**
- Reduce FPS (use `-r 20` instead of 25)
- Use lower quality (qscale 5 or 8)
- Reduce video resolution to 180x320

**SD card not mounting:**
- Check SD_CS pin (default GPIO5)
- Verify SD card is formatted FAT32
- Ensure /mjpeg folder exists on card

**Button not responding:**
- Make sure you're clicking BOOT (GPIO0), not the reset button
- Multi-click needs pauses between clicks (< 400ms)

---

## Performance Targets

| Metric | Target |
|--------|--------|
| Frame decode | < 30ms per frame (25fps budget: 40ms) |
| SPI transfer | < 15ms per frame |
| Total frame time | < 35ms (28fps effective) |
| Memory usage | < 300KB total |
| Startup time | < 2 seconds to first frame |

---

## File Format — .mjpeg

```
Each .mjpeg file = sequence of JPEG images concatenated:
[FF D8] [JPEG data] [FF D9] [FF D8] [JPEG data] [FF D9] ...

Resolution: 240x320 (or 180x320 for widescreen)
Color space: RGB565 (16-bit per pixel)
Frame rate: variable (set at encode time)
```

---

## Conversion Examples

```bash
# Movie clip to high quality
python3 tools/convert.py "/path/to/movie.mp4" -q high

# Animated clip at 20fps
python3 tools/convert.py "/path/to/cartoon.mp4" -r 20 -q ultra

# Widescreen video (will auto-pad to 240x320)
python3 tools/convert.py "/path/to/16_9.mp4" -q high

# Batch entire folder
python3 tools/convert.py ~/Videos/clips/ --batch -q medium

# Scan what's on your SD card
python3 tools/convert.py --scan /Volumes/ESPDISK
```

---

## Credits

- Original project: [thelastoutpostworkshop/esp32-2432S028_video_player](https://github.com/thelastoutpostworkshop/esp32-2432S028_video_player)
- JPEGDEC library: [bitbank2/JPEGDEC](https://github.com/bitbank2/JPEGDEC)
- Arduino GFX Library: [moononournation/Arduino_GFX](https://github.com/moononournation/Arduino_GFX)
- ESP-IDF: [espressif/esp-idf](https://github.com/espressif/esp-idf)
- FFmpeg: [ffmpeg.org](https://ffmpeg.org)