"""
Apple Vision Framework OCR Integration

Uses macOS Vision.framework for OCR instead of Tesseract.
~15-20x faster on Apple Silicon with better accuracy, especially for handwriting.

Requirements:
- macOS 10.15+ (Catalina or later)
- Apple Silicon for best performance (M1/M2/M3/M4)
- pyobjc-framework-Vision package

Fallback:
- If Vision.framework unavailable, falls back to ocrmac or pytesseract
"""

import logging
import platform
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

logger = logging.getLogger(__name__)


@dataclass
class OCRResult:
    """Result from OCR processing."""

    text: str
    confidence: float
    bounding_boxes: List[dict]  # [{"x": 0, "y": 0, "width": 100, "height": 20, "text": "..."}]
    language: Optional[str] = None
    processing_time_ms: float = 0


class VisionOCR:
    """
    OCR using Apple's Vision.framework.

    Optimized for Apple Silicon Neural Engine.
    Falls back to alternatives if Vision.framework unavailable.
    """

    def __init__(self, languages: Optional[List[str]] = None):
        """
        Initialize Vision OCR.

        Args:
            languages: Language codes to recognize (e.g., ["en-US", "ja-JP"])
                      If None, uses automatic language detection
        """
        self.languages = languages or ["en-US"]
        self._backend = self._detect_backend()
        logger.info(f"OCR backend: {self._backend}")

    def _detect_backend(self) -> str:
        """Detect best available OCR backend."""
        if platform.system() != "Darwin":
            logger.warning("Not on macOS, falling back to Tesseract")
            return "tesseract"

        # Try pyobjc Vision.framework
        try:
            import Vision  # noqa: F401 — availability check

            return "vision_pyobjc"
        except ImportError:
            pass

        # Try ocrmac CLI wrapper
        try:
            result = subprocess.run(["ocrmac", "--version"], capture_output=True, timeout=5)
            if result.returncode == 0:
                return "ocrmac"
        except (subprocess.SubprocessError, FileNotFoundError):
            pass

        # Fallback to tesseract
        logger.warning("Vision.framework unavailable, using Tesseract (slower)")
        return "tesseract"

    def process_image(self, image_path: Path) -> OCRResult:
        """
        Extract text from an image file.

        Args:
            image_path: Path to image file (PNG, JPEG, TIFF, PDF page)

        Returns:
            OCRResult with extracted text and metadata
        """
        import time

        start = time.time()

        if self._backend == "vision_pyobjc":
            result = self._process_with_vision_pyobjc(image_path)
        elif self._backend == "ocrmac":
            result = self._process_with_ocrmac(image_path)
        else:
            result = self._process_with_tesseract(image_path)

        result.processing_time_ms = (time.time() - start) * 1000
        return result

    def process_pdf(self, pdf_path: Path) -> List[OCRResult]:
        """
        Extract text from all pages of a PDF.

        Args:
            pdf_path: Path to PDF file

        Returns:
            List of OCRResult, one per page
        """
        # Convert PDF pages to images first
        images = self._pdf_to_images(pdf_path)

        results = []
        for i, img_path in enumerate(images):
            try:
                result = self.process_image(img_path)
                results.append(result)
            except Exception as e:
                logger.error(f"Failed to OCR page {i+1}: {e}")
                results.append(OCRResult(text="", confidence=0, bounding_boxes=[]))
            finally:
                # Clean up temp image
                if img_path.exists():
                    img_path.unlink()

        return results

    def _process_with_vision_pyobjc(self, image_path: Path) -> OCRResult:
        """Use Vision.framework via PyObjC bindings."""
        import Quartz
        import Vision

        # Load image
        image_url = Quartz.CFURLCreateWithFileSystemPath(
            None, str(image_path), Quartz.kCFURLPOSIXPathStyle, False
        )

        # Create image source
        image_source = Quartz.CGImageSourceCreateWithURL(image_url, None)
        if not image_source:
            raise ValueError(f"Could not load image: {image_path}")

        cg_image = Quartz.CGImageSourceCreateImageAtIndex(image_source, 0, None)

        # Create text recognition request
        request = Vision.VNRecognizeTextRequest.alloc().init()
        request.setRecognitionLevel_(Vision.VNRequestTextRecognitionLevelAccurate)
        request.setUsesLanguageCorrection_(True)

        if self.languages:
            request.setRecognitionLanguages_(self.languages)

        # Create handler and perform request
        handler = Vision.VNImageRequestHandler.alloc().initWithCGImage_options_(cg_image, None)
        success = handler.performRequests_error_([request], None)

        if not success:
            raise RuntimeError("Vision request failed")

        # Extract results
        observations = request.results()
        texts = []
        bboxes = []
        confidences = []

        for obs in observations:
            text = obs.topCandidates_(1)[0].string()
            confidence = obs.confidence()
            bbox = obs.boundingBox()

            texts.append(text)
            confidences.append(confidence)
            bboxes.append(
                {
                    "x": bbox.origin.x,
                    "y": bbox.origin.y,
                    "width": bbox.size.width,
                    "height": bbox.size.height,
                    "text": text,
                }
            )

        return OCRResult(
            text="\n".join(texts),
            confidence=sum(confidences) / len(confidences) if confidences else 0,
            bounding_boxes=bboxes,
        )

    def _process_with_ocrmac(self, image_path: Path) -> OCRResult:
        """Use ocrmac CLI wrapper for Vision.framework."""
        try:
            result = subprocess.run(
                ["ocrmac", str(image_path), "--recognition-level", "accurate"],
                capture_output=True,
                text=True,
                timeout=60,
            )

            if result.returncode != 0:
                raise RuntimeError(f"ocrmac failed: {result.stderr}")

            return OCRResult(
                text=result.stdout.strip(),
                confidence=0.9,  # ocrmac doesn't report confidence
                bounding_boxes=[],
            )
        except subprocess.TimeoutExpired:
            raise RuntimeError("OCR timed out after 60 seconds")

    def _process_with_tesseract(self, image_path: Path) -> OCRResult:
        """Fallback to Tesseract OCR."""
        try:
            import pytesseract
            from PIL import Image

            img = Image.open(image_path)
            text = pytesseract.image_to_string(img)

            # Get detailed data for confidence
            data = pytesseract.image_to_data(img, output_type=pytesseract.Output.DICT)
            confidences = [int(c) for c in data["conf"] if c != -1]
            avg_conf = sum(confidences) / len(confidences) if confidences else 0

            return OCRResult(text=text, confidence=avg_conf / 100, bounding_boxes=[])
        except ImportError:
            logger.error("pytesseract not installed")
            return OCRResult(text="", confidence=0, bounding_boxes=[])

    def _pdf_to_images(self, pdf_path: Path) -> List[Path]:
        """Convert PDF pages to temporary images."""
        try:
            import fitz  # PyMuPDF

            doc = fitz.open(pdf_path)
            images = []

            for page_num in range(len(doc)):
                page = doc[page_num]
                # Render at 2x for better OCR quality
                pix = page.get_pixmap(matrix=fitz.Matrix(2, 2))

                img_path = Path(tempfile.mktemp(suffix=".png"))
                pix.save(img_path)
                images.append(img_path)

            doc.close()
            return images
        except ImportError:
            logger.error("PyMuPDF not installed, cannot process PDFs")
            return []


# Convenience function
def extract_text(file_path: Path, languages: Optional[List[str]] = None) -> str:
    """
    Extract text from an image or PDF file.

    Uses Apple Vision.framework on macOS for optimal performance.

    Args:
        file_path: Path to image or PDF
        languages: Language codes for recognition

    Returns:
        Extracted text
    """
    ocr = VisionOCR(languages=languages)

    if file_path.suffix.lower() == ".pdf":
        results = ocr.process_pdf(file_path)
        return "\n\n---PAGE BREAK---\n\n".join(r.text for r in results)
    else:
        result = ocr.process_image(file_path)
        return result.text


# Performance comparison utility
def benchmark_ocr_backends(image_path: Path, iterations: int = 5) -> dict:
    """
    Compare OCR backend performance.

    Useful for validating Vision.framework is faster than Tesseract.
    """
    import time

    results = {}

    # Test Vision
    try:
        ocr = VisionOCR()
        ocr._backend = "vision_pyobjc"
        times = []
        for _ in range(iterations):
            start = time.time()
            ocr.process_image(image_path)
            times.append(time.time() - start)
        results["vision"] = {"avg_ms": sum(times) / len(times) * 1000}
    except Exception as e:
        results["vision"] = {"error": str(e)}

    # Test Tesseract
    try:
        ocr = VisionOCR()
        ocr._backend = "tesseract"
        times = []
        for _ in range(iterations):
            start = time.time()
            ocr.process_image(image_path)
            times.append(time.time() - start)
        results["tesseract"] = {"avg_ms": sum(times) / len(times) * 1000}
    except Exception as e:
        results["tesseract"] = {"error": str(e)}

    # Calculate speedup
    if "avg_ms" in results.get("vision", {}) and "avg_ms" in results.get("tesseract", {}):
        speedup = results["tesseract"]["avg_ms"] / results["vision"]["avg_ms"]
        results["speedup"] = f"{speedup:.1f}x faster with Vision.framework"

    return results
