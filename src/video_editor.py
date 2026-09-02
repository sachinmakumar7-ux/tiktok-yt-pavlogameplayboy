import os
import subprocess
import logging
from typing import Optional

logger = logging.getLogger(__name__)

class VideoEditor:
    @staticmethod
    def has_audio_stream(video_path: str) -> bool:
        if not os.path.exists(video_path):
            return False

        cmd = [
            "ffprobe",
            "-v", "error",
            "-select_streams", "a",
            "-show_entries", "stream=codec_name",
            "-of", "default=noprint_wrappers=1:nokey=1",
            video_path
        ]
        try:
            result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True)
            output = result.stdout.strip()
            return len(output) > 0
        except FileNotFoundError:
            logger.warning("ffprobe command not found. Skipping strict audio check (assume present).")
            return True
        except Exception as ex:
            logger.error(f"Error checking audio stream for {video_path}: {ex}")
            return False

    @classmethod
    def edit_and_optimize_short(
        cls,
        input_path: str,
        output_path: Optional[str] = None,
        apply_enhancements: bool = True
    ) -> Optional[str]:
        if not os.path.exists(input_path):
            logger.error(f"Input video does not exist: {input_path}")
            return None

        # 1. Verify Audio Stream
        if not cls.has_audio_stream(input_path):
            logger.error(f"Video {input_path} has NO audio track. Refusing to process silent video.")
            return None

        if output_path is None:
            dirname, filename = os.path.split(input_path)
            output_path = os.path.join(dirname, f"edited_{filename}")

        # 2. Build FFmpeg Filtergraph
        # - Scale & Pad to 1080x1920 (9:16 Shorts standard)
        # - Subtle contrast/saturation boost (1.03x contrast, +1% brightness, 1.05x saturation)
        # - Audio normalization (EBU R128 loudnorm target -14 LUFS)
        video_filters = [
            "scale=1080:1920:force_original_aspect_ratio=decrease",
            "pad=1080:1920:(ow-iw)/2:(oh-ih)/2:black"
        ]
        if apply_enhancements:
            video_filters.append("eq=contrast=1.03:brightness=0.01:saturation=1.05")

        vf_str = ",".join(video_filters)
        af_str = "loudnorm=I=-14:LRA=11:TP=-1.5"

        cmd = [
            "ffmpeg",
            "-y",
            "-i", input_path,
            "-vf", vf_str,
            "-af", af_str,
            "-c:v", "libx264",
            "-preset", "fast",
            "-crf", "20",
            "-c:a", "aac",
            "-b:a", "192k",
            "-ar", "48000",
            "-movflags", "+faststart",
            output_path
        ]

        logger.info(f"Applying automated edits and optimizations on: {input_path}...")
        try:
            res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True)
            if os.path.exists(output_path) and os.path.getsize(output_path) > 0:
                logger.info(f"Video successfully edited and saved at: {output_path}")
                return os.path.abspath(output_path)
        except FileNotFoundError:
            logger.warning("ffmpeg is not installed locally. Bypassing ffmpeg editing and using original file.")
            return os.path.abspath(input_path)
        except subprocess.CalledProcessError as cpe:
            logger.error(f"FFmpeg failed with error: {cpe.stderr}")
            # Fallback to original file if non-fatal
            return os.path.abspath(input_path)
        except Exception as ex:
            logger.error(f"Unexpected error during video editing: {ex}")
            return os.path.abspath(input_path)

        return None
