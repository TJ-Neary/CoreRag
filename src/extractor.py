import logging
import pypdf
import docx
from pathlib import Path

logger = logging.getLogger(__name__)

# File extensions handled by OCR
_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".tiff", ".tif", ".webp", ".bmp", ".heic"}

# Audio/video extensions
_AUDIO_EXTENSIONS = {".mp3", ".wav", ".m4a", ".flac", ".ogg", ".aac"}
_VIDEO_EXTENSIONS = {".mp4", ".mov", ".avi", ".mkv", ".webm"}

# Minimum characters from pypdf before we consider a PDF "text-based"
# Below this threshold, we assume it's scanned and fall back to OCR
_PDF_TEXT_THRESHOLD = 50


def extract_text(file_path: Path) -> str:
    """Extracts text content from supported file types.

    Supports: PDF (text + scanned via OCR), DOCX, TXT, MD, LOG, CSV, JSON, YAML,
    image files (PNG, JPG, JPEG, TIFF, WebP, BMP, HEIC) via Apple Vision OCR,
    audio files (MP3, WAV, M4A, FLAC, OGG, AAC) via Whisper transcription,
    and video files (MP4, MOV, AVI, MKV, WebM) via scene detection + transcription.
    """
    ext = file_path.suffix.lower()

    try:
        if ext == ".pdf":
            return _extract_pdf(file_path)
        elif ext == ".docx":
            return _extract_docx(file_path)
        elif ext in _IMAGE_EXTENSIONS:
            return _extract_image_ocr(file_path)
        elif ext in _AUDIO_EXTENSIONS:
            return _extract_audio(file_path)
        elif ext in _VIDEO_EXTENSIONS:
            return _extract_video(file_path)
        elif ext in [".txt", ".md", ".log", ".csv", ".json", ".yaml"]:
            return file_path.read_text(errors="replace")
        else:
            logger.warning(f"Unsupported file type: {ext}. Skipping extraction.")
            return ""
    except Exception as e:
        logger.error(f"Error extracting text from {file_path.name}: {e}")
        return ""


def _extract_pdf(path: Path) -> str:
    """Extract text from PDF, falling back to OCR for scanned documents."""
    # First try text-based extraction (fast)
    text = ""
    with open(path, "rb") as f:
        reader = pypdf.PdfReader(f)
        for page in reader.pages:
            extracted = page.extract_text()
            if extracted:
                text += extracted + "\n"

    # If we got meaningful text, return it
    if len(text.strip()) >= _PDF_TEXT_THRESHOLD:
        return text

    # Scanned PDF — fall back to OCR
    logger.info(f"PDF has little/no text ({len(text.strip())} chars), trying OCR: {path.name}")
    return _extract_pdf_ocr(path)


def _extract_docx(path: Path) -> str:
    doc = docx.Document(path)
    return "\n".join([p.text for p in doc.paragraphs])


def _extract_image_ocr(image_path: Path) -> str:
    """Extract text from an image file using Apple Vision OCR + optional VLM captioning."""
    ocr_text = ""
    try:
        from src.ocr.vision_ocr import VisionOCR

        ocr = VisionOCR()
        result = ocr.process_image(image_path)
        ocr_text = result.text
        logger.info(
            f"OCR extracted {len(result.text)} chars from {image_path.name} "
            f"(confidence: {result.confidence:.2f}, backend: {ocr._backend}, "
            f"time: {result.processing_time_ms:.0f}ms)"
        )
    except Exception as e:
        logger.error(f"OCR failed for image {image_path.name}: {e}")

    # VLM captioning for richer searchable text (diagrams, photos, charts)
    caption_text = ""
    try:
        from src.multimodal.vlm_captioner import VLMCaptioner

        captioner = VLMCaptioner()
        is_diagram = any(
            kw in ocr_text.lower()
            for kw in ["flowchart", "diagram", "->", "-->", "graph", "chart"]
        )
        caption = captioner.caption_image(image_path, is_diagram=is_diagram)
        caption_text = caption.caption
        logger.info(
            f"VLM caption for {image_path.name}: {len(caption_text)} chars "
            f"(model: {caption.model_used}, time: {caption.processing_time_ms:.0f}ms)"
        )
    except ImportError:
        logger.debug(f"VLM captioner not available for {image_path.name}")
    except Exception as e:
        logger.warning(f"VLM captioning failed for {image_path.name}: {e}")

    # Combine OCR text + VLM caption into searchable document
    parts = []
    if ocr_text.strip():
        parts.append(ocr_text)
    if caption_text.strip():
        parts.append(f"\n## Image Description\n{caption_text}")

    return "\n\n".join(parts) if parts else ""


def _extract_pdf_ocr(pdf_path: Path) -> str:
    """Extract text from a scanned PDF using Apple Vision OCR."""
    try:
        from src.ocr.vision_ocr import VisionOCR

        ocr = VisionOCR()
        results = ocr.process_pdf(pdf_path)
        pages_text = [r.text for r in results if r.text.strip()]

        if pages_text:
            total_chars = sum(len(t) for t in pages_text)
            avg_confidence = (
                sum(r.confidence for r in results if r.text.strip()) / len(pages_text)
            )
            logger.info(
                f"OCR extracted {total_chars} chars from {len(pages_text)}/{len(results)} pages "
                f"of {pdf_path.name} (avg confidence: {avg_confidence:.2f})"
            )
        else:
            logger.warning(f"OCR produced no text from {pdf_path.name}")

        return "\n\n".join(pages_text)
    except Exception as e:
        logger.error(f"OCR failed for PDF {pdf_path.name}: {e}")
        return ""


def _extract_audio(audio_path: Path) -> str:
    """Extract text from audio via Whisper transcription + topic segmentation."""
    try:
        import asyncio
        from src.audio.topic_segmentation import WhisperWithSegmentation

        transcriber = WhisperWithSegmentation()

        # Run async transcription in sync context
        loop = asyncio.new_event_loop()
        try:
            segmented = loop.run_until_complete(
                transcriber.transcribe_and_segment(audio_path)
            )
        finally:
            loop.close()

        if segmented.chapters:
            # Format as chaptered document for better chunking
            parts = []
            for ch in segmented.chapters:
                header = f"## {ch.title}"
                parts.append(f"{header}\n\n{ch.content}")
            text = "\n\n".join(parts)
            logger.info(
                f"Audio transcribed: {audio_path.name} — {len(segmented.chapters)} chapters, "
                f"{len(segmented.raw_transcript)} chars"
            )
            return text

        # Fallback: return raw transcript
        logger.info(f"Audio transcribed (no chapters): {audio_path.name} — {len(segmented.raw_transcript)} chars")
        return segmented.raw_transcript

    except ImportError:
        logger.warning(f"Audio transcription unavailable (mlx-whisper not installed): {audio_path.name}")
        return ""
    except Exception as e:
        logger.error(f"Audio extraction failed for {audio_path.name}: {e}")
        return ""


def _extract_video(video_path: Path) -> str:
    """Extract text from video via scene detection + optional transcription."""
    try:
        from src.video.scene_detector import VideoProcessor

        processor = VideoProcessor()
        analysis = processor.process_video(
            video_path,
            extract_audio=True,
            caption_keyframes=False,  # VLM captioning is optional/expensive
        )

        text = analysis.as_searchable_document()
        logger.info(
            f"Video processed: {video_path.name} — {len(analysis.keyframes)} keyframes, "
            f"{analysis.duration_seconds:.0f}s duration"
        )
        return text

    except ImportError:
        logger.warning(f"Video processing unavailable (opencv-python not installed): {video_path.name}")
        return ""
    except Exception as e:
        logger.error(f"Video extraction failed for {video_path.name}: {e}")
        return ""
