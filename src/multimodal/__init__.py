"""Multimodal module for processing images, video, and other media types."""

from .vlm_captioner import ImageCaption, VLMCaptioner

__all__ = ["VLMCaptioner", "ImageCaption"]
