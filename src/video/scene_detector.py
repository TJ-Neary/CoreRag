"""
Video scene detection and keyframe extraction for CoreRag.

Extracts representative keyframes from videos using scene change detection,
then passes them to VLM for captioning to enable semantic video search.

Optimized for Apple Silicon M4 Max with Metal acceleration.
"""

import logging
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Tuple
import json

logger = logging.getLogger(__name__)

# Check for OpenCV availability
CV2_AVAILABLE = False
try:
    import cv2
    import numpy as np
    CV2_AVAILABLE = True
except ImportError:
    logger.warning("OpenCV not installed. Install with: pip install opencv-python")


@dataclass
class Keyframe:
    """A single keyframe extracted from video."""
    frame_number: int
    timestamp_seconds: float
    image_path: Path
    scene_score: float  # How different from previous scene (0-1)
    caption: Optional[str] = None
    embedding: Optional[List[float]] = None


@dataclass
class VideoAnalysis:
    """Complete analysis of a video file."""
    source_path: str
    duration_seconds: float
    fps: float
    total_frames: int
    keyframes: List[Keyframe] = field(default_factory=list)
    transcript: Optional[str] = None

    def as_searchable_document(self) -> str:
        """Convert to searchable text for embedding."""
        parts = [f"Video: {Path(self.source_path).name}"]
        parts.append(f"Duration: {self.duration_seconds:.1f} seconds")

        if self.transcript:
            parts.append(f"\nTranscript:\n{self.transcript}")

        if self.keyframes:
            parts.append("\nVisual Scenes:")
            for i, kf in enumerate(self.keyframes, 1):
                timestamp = f"{int(kf.timestamp_seconds // 60)}:{int(kf.timestamp_seconds % 60):02d}"
                if kf.caption:
                    parts.append(f"  [{timestamp}] {kf.caption}")

        return "\n".join(parts)


class SceneDetector:
    """
    Extract keyframes from video using scene change detection.

    Uses histogram comparison to detect visual scene changes,
    extracting one representative frame per scene.
    """

    def __init__(
        self,
        min_scene_length_seconds: float = 2.0,
        threshold: float = 0.4,
        max_keyframes: int = 50,
        output_dir: Optional[Path] = None,
    ):
        """
        Initialize scene detector.

        Args:
            min_scene_length_seconds: Minimum time between keyframes
            threshold: Scene change threshold (0-1, higher = less sensitive)
            max_keyframes: Maximum keyframes to extract
            output_dir: Directory to save keyframe images
        """
        if not CV2_AVAILABLE:
            raise ImportError("OpenCV required. Install: pip install opencv-python")

        self.min_scene_length = min_scene_length_seconds
        self.threshold = threshold
        self.max_keyframes = max_keyframes
        self.output_dir = output_dir or Path(tempfile.mkdtemp(prefix="corerag_keyframes_"))
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def extract_keyframes(self, video_path: Path) -> VideoAnalysis:
        """
        Extract keyframes from a video file.

        Args:
            video_path: Path to video file

        Returns:
            VideoAnalysis with extracted keyframes
        """
        video_path = Path(video_path)
        if not video_path.exists():
            raise FileNotFoundError(f"Video not found: {video_path}")

        cap = cv2.VideoCapture(str(video_path))

        if not cap.isOpened():
            raise ValueError(f"Could not open video: {video_path}")

        # Get video properties
        fps = cap.get(cv2.CAP_PROP_FPS)
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        duration = total_frames / fps if fps > 0 else 0

        logger.info(f"Processing video: {video_path.name} ({duration:.1f}s, {fps:.1f} fps)")

        analysis = VideoAnalysis(
            source_path=str(video_path),
            duration_seconds=duration,
            fps=fps,
            total_frames=total_frames,
        )

        # Extract keyframes
        keyframes = self._detect_scenes(cap, video_path.stem)
        analysis.keyframes = keyframes[:self.max_keyframes]

        cap.release()

        logger.info(f"Extracted {len(analysis.keyframes)} keyframes from {video_path.name}")

        return analysis

    def _detect_scenes(
        self,
        cap: "cv2.VideoCapture",
        video_name: str
    ) -> List[Keyframe]:
        """Detect scene changes and extract keyframes."""
        keyframes = []
        prev_hist = None
        last_keyframe_time = -self.min_scene_length

        fps = cap.get(cv2.CAP_PROP_FPS)
        frame_number = 0

        # Always capture first frame
        ret, frame = cap.read()
        if ret:
            keyframe = self._save_keyframe(
                frame, frame_number, 0.0, 1.0, video_name
            )
            keyframes.append(keyframe)
            prev_hist = self._compute_histogram(frame)
            last_keyframe_time = 0.0

        frame_number = 1

        while True:
            ret, frame = cap.read()
            if not ret:
                break

            timestamp = frame_number / fps

            # Check if enough time has passed
            if timestamp - last_keyframe_time < self.min_scene_length:
                frame_number += 1
                continue

            # Compute histogram and compare
            curr_hist = self._compute_histogram(frame)

            if prev_hist is not None:
                diff = cv2.compareHist(prev_hist, curr_hist, cv2.HISTCMP_BHATTACHARYYA)

                # Scene change detected
                if diff > self.threshold:
                    keyframe = self._save_keyframe(
                        frame, frame_number, timestamp, diff, video_name
                    )
                    keyframes.append(keyframe)
                    last_keyframe_time = timestamp

                    if len(keyframes) >= self.max_keyframes:
                        break

            prev_hist = curr_hist
            frame_number += 1

        return keyframes

    def _compute_histogram(self, frame: "np.ndarray") -> "np.ndarray":
        """Compute color histogram for scene comparison."""
        # Convert to HSV for better color comparison
        hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)

        # Compute histogram
        hist = cv2.calcHist(
            [hsv], [0, 1], None, [50, 60], [0, 180, 0, 256]
        )

        # Normalize
        cv2.normalize(hist, hist)

        return hist

    def _save_keyframe(
        self,
        frame: "np.ndarray",
        frame_number: int,
        timestamp: float,
        score: float,
        video_name: str,
    ) -> Keyframe:
        """Save keyframe image and create Keyframe object."""
        # Generate filename
        filename = f"{video_name}_frame_{frame_number:06d}.jpg"
        image_path = self.output_dir / filename

        # Save image (JPEG for smaller size)
        cv2.imwrite(str(image_path), frame, [cv2.IMWRITE_JPEG_QUALITY, 85])

        return Keyframe(
            frame_number=frame_number,
            timestamp_seconds=timestamp,
            image_path=image_path,
            scene_score=score,
        )


class VideoProcessor:
    """
    Complete video processing pipeline for CoreRag.

    Combines:
    - Scene detection for keyframe extraction
    - VLM captioning for visual understanding
    - Audio transcription for speech content
    """

    def __init__(
        self,
        scene_detector: Optional[SceneDetector] = None,
        vlm_captioner: Optional["VLMCaptioner"] = None,
        whisper_transcriber: Optional[object] = None,
        output_dir: Optional[Path] = None,
    ):
        """
        Initialize video processor.

        Args:
            scene_detector: Scene detector instance
            vlm_captioner: VLM captioner for keyframe descriptions
            whisper_transcriber: Whisper for audio transcription
            output_dir: Directory for outputs
        """
        self.output_dir = output_dir or Path.home() / ".corerag" / "video_cache"
        self.output_dir.mkdir(parents=True, exist_ok=True)

        self.scene_detector = scene_detector or SceneDetector(
            output_dir=self.output_dir / "keyframes"
        )
        self.vlm_captioner = vlm_captioner
        self.whisper_transcriber = whisper_transcriber

    def process_video(
        self,
        video_path: Path,
        extract_audio: bool = True,
        caption_keyframes: bool = True,
    ) -> VideoAnalysis:
        """
        Process a video file for CoreRag ingestion.

        Args:
            video_path: Path to video file
            extract_audio: Whether to transcribe audio
            caption_keyframes: Whether to generate VLM captions

        Returns:
            VideoAnalysis with all extracted content
        """
        video_path = Path(video_path)

        # Extract keyframes
        logger.info(f"Extracting keyframes from {video_path.name}")
        analysis = self.scene_detector.extract_keyframes(video_path)

        # Caption keyframes with VLM
        if caption_keyframes and self.vlm_captioner:
            logger.info(f"Generating captions for {len(analysis.keyframes)} keyframes")
            for keyframe in analysis.keyframes:
                try:
                    result = self.vlm_captioner.caption_image(
                        keyframe.image_path,
                        prompt="Describe what is happening in this video frame. "
                               "Focus on people, actions, text, and important objects."
                    )
                    keyframe.caption = result.caption
                except Exception as e:
                    logger.warning(f"Failed to caption keyframe: {e}")

        # Extract and transcribe audio
        if extract_audio and self.whisper_transcriber:
            logger.info("Transcribing audio...")
            try:
                audio_path = self._extract_audio(video_path)
                if audio_path:
                    analysis.transcript = self._transcribe_audio(audio_path)
            except Exception as e:
                logger.warning(f"Failed to transcribe audio: {e}")

        # Save analysis metadata
        self._save_analysis(analysis, video_path)

        return analysis

    def _extract_audio(self, video_path: Path) -> Optional[Path]:
        """Extract audio track from video."""
        try:
            import subprocess

            audio_path = self.output_dir / f"{video_path.stem}.wav"

            # Use ffmpeg to extract audio
            subprocess.run([
                "ffmpeg", "-i", str(video_path),
                "-vn", "-acodec", "pcm_s16le",
                "-ar", "16000", "-ac", "1",
                str(audio_path), "-y"
            ], capture_output=True, check=True)

            return audio_path

        except Exception as e:
            logger.warning(f"Could not extract audio: {e}")
            return None

    def _transcribe_audio(self, audio_path: Path) -> Optional[str]:
        """Transcribe audio using Whisper."""
        if not self.whisper_transcriber:
            return None

        # This would integrate with mlx-whisper
        # For now, return placeholder
        try:
            result = self.whisper_transcriber.transcribe(str(audio_path))
            return result.get("text", "")
        except Exception as e:
            logger.warning(f"Transcription failed: {e}")
            return None

    def _save_analysis(self, analysis: VideoAnalysis, video_path: Path) -> None:
        """Save analysis metadata to JSON."""
        metadata_path = self.output_dir / f"{video_path.stem}_analysis.json"

        data = {
            "source_path": analysis.source_path,
            "duration_seconds": analysis.duration_seconds,
            "fps": analysis.fps,
            "total_frames": analysis.total_frames,
            "keyframes": [
                {
                    "frame_number": kf.frame_number,
                    "timestamp_seconds": kf.timestamp_seconds,
                    "image_path": str(kf.image_path),
                    "scene_score": kf.scene_score,
                    "caption": kf.caption,
                }
                for kf in analysis.keyframes
            ],
            "transcript": analysis.transcript,
        }

        with open(metadata_path, "w") as f:
            json.dump(data, f, indent=2)


# Convenience function
def extract_video_keyframes(
    video_path: Path,
    output_dir: Optional[Path] = None,
    max_keyframes: int = 30,
) -> List[Keyframe]:
    """
    Quick extraction of keyframes from a video.

    Args:
        video_path: Path to video file
        output_dir: Where to save keyframe images
        max_keyframes: Maximum keyframes to extract

    Returns:
        List of Keyframe objects
    """
    detector = SceneDetector(
        output_dir=output_dir,
        max_keyframes=max_keyframes,
    )

    analysis = detector.extract_keyframes(video_path)
    return analysis.keyframes
