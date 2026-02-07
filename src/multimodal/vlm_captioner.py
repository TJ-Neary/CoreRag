"""
VLM (Vision Language Model) Captioning

Generates detailed text descriptions of images for searchable indexing.
CLIP gives similarity; VLM gives understanding.

Workflow:
1. Image ingested
2. VLM generates description: "A flowchart showing server architecture with..."
3. Description indexed as text, making image content searchable
"""

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

logger = logging.getLogger(__name__)


@dataclass
class ImageCaption:
    """Caption generated for an image."""

    image_path: str
    caption: str
    model_used: str
    confidence: float
    processing_time_ms: float
    metadata: dict


class VLMCaptioner:
    """
    Generates captions for images using Vision Language Models.

    Supports:
    - Moondream2 (tiny, fast, runs on MLX)
    - Qwen2.5-VL (better quality)
    - LLaVA (alternative)

    All models run locally on M4 Max.
    """

    CAPTION_PROMPT = """Describe this image in detail. Focus on:
- Text content visible in the image
- Diagrams, charts, or flowcharts and their structure
- Key visual elements and their relationships
- Any data or information presented

Be specific and thorough. This description will be used for search indexing."""

    DIAGRAM_PROMPT = """This image appears to be a diagram or technical illustration.
Describe:
1. The type of diagram (flowchart, architecture, sequence, etc.)
2. The main components or nodes
3. The relationships or connections between them
4. Any labels, text, or annotations
5. The overall purpose or concept being illustrated"""

    def __init__(self, model_name: str = "vikhyatk/moondream2", backend: str = "auto"):
        """
        Args:
            model_name: VLM model to use
            backend: "mlx", "transformers", or "auto"
        """
        self.model_name = model_name
        self.backend = self._detect_backend(backend)
        self._model = None
        self._processor = None
        logger.info(f"VLM Captioner: {model_name} on {self.backend}")

    def _detect_backend(self, requested: str) -> str:
        """Detect best available backend."""
        if requested != "auto":
            return requested

        try:
            import platform

            import mlx.core  # noqa: F401 — availability check

            if platform.processor() == "arm":
                return "mlx"
        except ImportError:
            pass

        return "transformers"

    def _load_model(self):
        """Lazy-load the VLM model."""
        if self._model is not None:
            return

        if self.backend == "mlx":
            self._load_mlx_model()
        else:
            self._load_transformers_model()

    def _load_mlx_model(self):
        """Load model for MLX inference."""
        try:
            # MLX-VLM loading (if available)
            # This is model-specific; Moondream2 has MLX support
            from mlx_vlm import generate, load

            self._model, self._processor = load(self.model_name)
            self._generate = generate
            logger.info(f"Loaded {self.model_name} with MLX")
        except ImportError:
            logger.warning("MLX-VLM not available, falling back to transformers")
            self.backend = "transformers"
            self._load_transformers_model()

    def _load_transformers_model(self):
        """Load model using transformers."""
        import torch
        from transformers import AutoModelForVision2Seq, AutoProcessor

        self._processor = AutoProcessor.from_pretrained(self.model_name)  # nosec B615
        self._model = AutoModelForVision2Seq.from_pretrained(  # nosec B615
            self.model_name,
            torch_dtype=torch.float16 if torch.cuda.is_available() else torch.float32,
            device_map="auto",
        )
        logger.info(f"Loaded {self.model_name} with transformers")

    def caption_image(
        self, image_path: Path, prompt: Optional[str] = None, is_diagram: bool = False
    ) -> ImageCaption:
        """
        Generate a caption for an image.

        Args:
            image_path: Path to image file
            prompt: Custom prompt (uses default if None)
            is_diagram: Use diagram-specific prompt

        Returns:
            ImageCaption with generated description
        """
        import time

        start = time.time()

        self._load_model()

        # Select prompt
        if prompt is None:
            prompt = self.DIAGRAM_PROMPT if is_diagram else self.CAPTION_PROMPT

        # Load image
        from PIL import Image

        image = Image.open(image_path)

        # Generate caption
        if self.backend == "mlx":
            caption = self._caption_mlx(image, prompt)
        else:
            caption = self._caption_transformers(image, prompt)

        processing_time = (time.time() - start) * 1000

        return ImageCaption(
            image_path=str(image_path),
            caption=caption,
            model_used=self.model_name,
            confidence=0.9,  # VLMs don't typically output confidence
            processing_time_ms=processing_time,
            metadata={
                "image_size": image.size,
                "is_diagram": is_diagram,
                "prompt_type": "diagram" if is_diagram else "general",
            },
        )

    def _caption_mlx(self, image, prompt: str) -> str:
        """Generate caption using MLX."""
        output = self._generate(self._model, self._processor, image, prompt, max_tokens=500)
        return output

    def _caption_transformers(self, image, prompt: str) -> str:
        """Generate caption using transformers."""
        assert self._processor is not None
        assert self._model is not None
        inputs = self._processor(text=prompt, images=image, return_tensors="pt")

        if hasattr(self._model, "device"):
            inputs = {k: v.to(self._model.device) for k, v in inputs.items()}

        outputs = self._model.generate(**inputs, max_new_tokens=500, do_sample=False)

        caption = self._processor.decode(outputs[0], skip_special_tokens=True)

        # Remove the prompt from output if echoed
        if caption.startswith(prompt):
            caption = caption[len(prompt) :].strip()

        return caption

    def caption_pdf_images(
        self, pdf_path: Path, extract_diagrams: bool = True
    ) -> List[ImageCaption]:
        """
        Extract and caption images from a PDF.

        Args:
            pdf_path: Path to PDF file
            extract_diagrams: Also extract diagrams/charts

        Returns:
            List of captions for each image
        """
        import tempfile

        try:
            import fitz  # PyMuPDF
        except ImportError:
            logger.error("PyMuPDF required for PDF image extraction")
            return []

        doc = fitz.open(pdf_path)
        captions = []

        for page_num in range(len(doc)):
            page = doc[page_num]

            # Extract images
            for img_index, img in enumerate(page.get_images()):
                xref = img[0]
                base_image = doc.extract_image(xref)
                image_bytes = base_image["image"]
                image_ext = base_image["ext"]

                # Save to temp file
                with tempfile.NamedTemporaryFile(suffix=f".{image_ext}", delete=False) as tmp:
                    tmp.write(image_bytes)
                    tmp_path = Path(tmp.name)

                try:
                    # Determine if likely a diagram
                    is_diagram = self._is_likely_diagram(tmp_path)

                    caption = self.caption_image(tmp_path, is_diagram=is_diagram)
                    caption.metadata["pdf_page"] = page_num + 1
                    caption.metadata["image_index"] = img_index
                    captions.append(caption)

                finally:
                    # Cleanup temp file
                    tmp_path.unlink()

        doc.close()
        return captions

    def _is_likely_diagram(self, image_path: Path) -> bool:
        """Heuristic to detect if image is likely a diagram."""
        import numpy as np
        from PIL import Image

        img = Image.open(image_path).convert("RGB")
        arr = np.array(img)

        # Diagrams tend to have:
        # - Limited color palette
        # - High contrast
        # - More white space

        # Count unique colors (diagrams have fewer)
        unique_colors = len(np.unique(arr.reshape(-1, 3), axis=0))

        # Check white space ratio
        white_pixels = np.sum(np.all(arr > 240, axis=2))
        total_pixels = arr.shape[0] * arr.shape[1]
        white_ratio = white_pixels / total_pixels

        # Heuristic thresholds
        return unique_colors < 1000 and white_ratio > 0.3


def create_shadow_document(image_path: Path, caption: ImageCaption, output_dir: Path) -> Path:
    """
    Create a "shadow document" for an image.

    The shadow document contains the VLM-generated description
    and is indexed alongside the original image.

    Args:
        image_path: Original image path
        caption: Generated caption
        output_dir: Directory for shadow documents

    Returns:
        Path to created shadow document
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    shadow_path = output_dir / f"{image_path.stem}.shadow.md"

    content = f"""# Image Description: {image_path.name}

**Source Image**: {image_path}
**Generated by**: {caption.model_used}
**Generated at**: {caption.metadata.get('timestamp', 'unknown')}

## Description

{caption.caption}

## Metadata

- Image Size: {caption.metadata.get('image_size', 'unknown')}
- Diagram Type: {'Yes' if caption.metadata.get('is_diagram') else 'No'}
- Processing Time: {caption.processing_time_ms:.1f}ms
"""

    shadow_path.write_text(content)
    logger.info(f"Created shadow document: {shadow_path}")

    return shadow_path
