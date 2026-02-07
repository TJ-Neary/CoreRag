"""
Audio Topic Segmentation

Segments transcripts into semantic chapters before chunking.
"Chapter 3: Discussion on Q3 Goals" is more useful than "Fragment 45".

Workflow:
1. Whisper transcribes audio
2. LLM identifies topic shifts
3. Chapter markers inserted
4. Chunking respects chapter boundaries
"""

import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple

logger = logging.getLogger(__name__)


@dataclass
class Chapter:
    """A semantic chapter in audio/transcript."""

    title: str
    start_time: float  # seconds
    end_time: float
    content: str
    chapter_number: int
    summary: Optional[str] = None


@dataclass
class SegmentedTranscript:
    """Transcript with semantic chapters."""

    source_file: str
    total_duration: float
    chapters: List[Chapter]
    raw_transcript: str

    @property
    def chapter_count(self) -> int:
        return len(self.chapters)


class TopicSegmenter:
    """
    Segments transcripts into semantic topics/chapters.

    Uses a small local LLM (Llama-3.2-3B) to detect topic shifts.
    Falls back to heuristics if LLM unavailable.
    """

    SEGMENTATION_PROMPT = """Analyze this transcript and identify where the topic changes significantly.

Transcript:
{transcript}

Output a JSON array of chapter markers:
[
  {{"time": "00:00", "title": "Introduction", "summary": "Brief overview of..."}},
  {{"time": "05:32", "title": "Main Topic 1", "summary": "Discussion about..."}},
  ...
]

Focus on major topic shifts, not minor transitions.
Aim for 3-10 chapters for a typical conversation.

JSON:"""

    def __init__(self, llm=None, min_chapter_seconds: int = 60):
        """
        Args:
            llm: Local LLM for segmentation (optional)
            min_chapter_seconds: Minimum chapter length
        """
        self.llm = llm
        self.min_chapter_seconds = min_chapter_seconds

    async def segment(
        self,
        transcript: str,
        timestamps: Optional[List[Tuple[float, str]]] = None,
        source_file: Optional[str] = None,
        total_duration: Optional[float] = None,
    ) -> SegmentedTranscript:
        """
        Segment transcript into chapters.

        Args:
            transcript: Full transcript text
            timestamps: Optional list of (time_seconds, text) tuples
            source_file: Source audio/video file path
            total_duration: Total duration in seconds

        Returns:
            SegmentedTranscript with chapters
        """
        if self.llm:
            chapters = await self._segment_with_llm(transcript, timestamps)
        else:
            chapters = self._segment_with_heuristics(transcript, timestamps)

        # Assign content to chapters
        if timestamps:
            chapters = self._assign_content_by_time(chapters, timestamps)
        else:
            chapters = self._assign_content_by_position(chapters, transcript)

        return SegmentedTranscript(
            source_file=source_file or "unknown",
            total_duration=total_duration or 0,
            chapters=chapters,
            raw_transcript=transcript,
        )

    async def _segment_with_llm(
        self, transcript: str, timestamps: Optional[List[Tuple[float, str]]]
    ) -> List[Chapter]:
        """Segment using LLM."""
        try:
            # Truncate for LLM context
            prompt = self.SEGMENTATION_PROMPT.format(transcript=transcript[:8000])

            response = await self.llm.generate(prompt, max_tokens=1000)

            # Parse JSON
            import json

            json_match = re.search(r"\[[\s\S]*\]", response)
            if not json_match:
                logger.warning("LLM didn't return valid JSON, using heuristics")
                return self._segment_with_heuristics(transcript, timestamps)

            markers = json.loads(json_match.group())

            chapters = []
            for i, marker in enumerate(markers):
                time_str = marker.get("time", "00:00")
                time_seconds = self._parse_time(time_str)

                chapters.append(
                    Chapter(
                        title=marker.get("title", f"Chapter {i+1}"),
                        start_time=time_seconds,
                        end_time=0,  # Set later
                        content="",  # Filled later
                        chapter_number=i + 1,
                        summary=marker.get("summary"),
                    )
                )

            # Set end times
            for i in range(len(chapters) - 1):
                chapters[i].end_time = chapters[i + 1].start_time

            return chapters

        except Exception as e:
            logger.warning(f"LLM segmentation failed: {e}, using heuristics")
            return self._segment_with_heuristics(transcript, timestamps)

    def _segment_with_heuristics(
        self, transcript: str, timestamps: Optional[List[Tuple[float, str]]]
    ) -> List[Chapter]:
        """Segment using heuristics (fallback)."""
        chapters = []

        # Split on common topic transition markers
        transition_patterns = [
            r"\b(now|next|moving on|let\'s talk about|turning to)\b",
            r"\b(another thing|speaking of|on the topic of)\b",
            r"\b(so|okay|alright)[\s,]+(let\'s|we\'ll|I\'ll)\b",
            r"(\?\s*$)",  # Questions often indicate topic shifts
        ]

        combined_pattern = "|".join(f"({p})" for p in transition_patterns)

        # Find potential breaks
        breaks = [0]
        for match in re.finditer(combined_pattern, transcript, re.IGNORECASE):
            pos = match.start()
            # Ensure minimum distance between breaks
            if pos - breaks[-1] > len(transcript) // 10:
                breaks.append(pos)

        # Create chapters
        for i, start_pos in enumerate(breaks):
            end_pos = breaks[i + 1] if i + 1 < len(breaks) else len(transcript)
            content = transcript[start_pos:end_pos].strip()

            # Generate title from first sentence
            first_sentence = content.split(".")[0][:100]
            title = f"Chapter {i + 1}: {first_sentence}..."

            chapters.append(
                Chapter(
                    title=title,
                    start_time=0,  # Can't determine without timestamps
                    end_time=0,
                    content=content,
                    chapter_number=i + 1,
                )
            )

        return (
            chapters
            if chapters
            else [
                Chapter(
                    title="Full Recording",
                    start_time=0,
                    end_time=0,
                    content=transcript,
                    chapter_number=1,
                )
            ]
        )

    def _assign_content_by_time(
        self, chapters: List[Chapter], timestamps: List[Tuple[float, str]]
    ) -> List[Chapter]:
        """Assign transcript content based on timestamps."""
        for chapter in chapters:
            content_parts = []
            for time_sec, text in timestamps:
                if chapter.start_time <= time_sec < (chapter.end_time or float("inf")):
                    content_parts.append(text)
            chapter.content = " ".join(content_parts)
        return chapters

    def _assign_content_by_position(
        self, chapters: List[Chapter], transcript: str
    ) -> List[Chapter]:
        """Assign content based on position (when no timestamps)."""
        # Already assigned during heuristic segmentation
        return chapters

    def _parse_time(self, time_str: str) -> float:
        """Parse time string to seconds."""
        parts = time_str.split(":")
        if len(parts) == 2:
            return int(parts[0]) * 60 + float(parts[1])
        elif len(parts) == 3:
            return int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
        return 0


class WhisperWithSegmentation:
    """
    Wrapper around Whisper that adds topic segmentation.

    Usage:
        whisper = WhisperWithSegmentation()
        result = await whisper.transcribe_and_segment(audio_path)
        for chapter in result.chapters:
            print(f"{chapter.title}: {chapter.content[:100]}...")
    """

    def __init__(self, whisper_model: str = "large-v3", llm=None):
        self.whisper_model = whisper_model
        self.segmenter = TopicSegmenter(llm=llm)
        self._whisper = None

    def _load_whisper(self):
        """Lazy-load Whisper model."""
        if self._whisper is not None:
            return

        try:
            import mlx_whisper

            self._whisper = mlx_whisper
            self._backend = "mlx"
        except ImportError:
            import whisper

            self._whisper = whisper.load_model(self.whisper_model)
            self._backend = "openai"

    async def transcribe_and_segment(self, audio_path: Path) -> SegmentedTranscript:
        """
        Transcribe audio and segment into chapters.

        Args:
            audio_path: Path to audio file

        Returns:
            SegmentedTranscript with chapters
        """
        self._load_whisper()

        assert self._whisper is not None
        # Transcribe
        if self._backend == "mlx":
            result = self._whisper.transcribe(
                str(audio_path), path_or_hf_repo=f"mlx-community/whisper-{self.whisper_model}"
            )
        else:
            result = self._whisper.transcribe(str(audio_path))

        # Extract text and timestamps
        transcript = result["text"]
        segments = result.get("segments", [])

        timestamps = [(seg["start"], seg["text"]) for seg in segments]

        total_duration = segments[-1]["end"] if segments else 0

        # Segment into chapters
        segmented = await self.segmenter.segment(
            transcript=transcript,
            timestamps=timestamps,
            source_file=str(audio_path),
            total_duration=total_duration,
        )

        return segmented


def chunk_by_chapters(
    segmented: SegmentedTranscript, max_tokens_per_chunk: int = 500
) -> List[dict]:
    """
    Chunk transcript by chapters, respecting semantic boundaries.

    Each chunk includes chapter context for better retrieval.
    """
    chunks = []

    for chapter in segmented.chapters:
        # If chapter fits in one chunk
        tokens_estimate = len(chapter.content) // 4

        if tokens_estimate <= max_tokens_per_chunk:
            chunks.append(
                {
                    "content": chapter.content,
                    "chapter_title": chapter.title,
                    "chapter_number": chapter.chapter_number,
                    "start_time": chapter.start_time,
                    "end_time": chapter.end_time,
                    "source_file": segmented.source_file,
                }
            )
        else:
            # Split large chapter into sub-chunks
            sentences = re.split(r"(?<=[.!?])\s+", chapter.content)
            current_chunk: list[str] = []
            current_tokens = 0

            for sentence in sentences:
                sent_tokens = len(sentence) // 4

                if current_tokens + sent_tokens > max_tokens_per_chunk and current_chunk:
                    chunks.append(
                        {
                            "content": " ".join(current_chunk),
                            "chapter_title": chapter.title,
                            "chapter_number": chapter.chapter_number,
                            "start_time": chapter.start_time,
                            "source_file": segmented.source_file,
                        }
                    )
                    current_chunk = []
                    current_tokens = 0

                current_chunk.append(sentence)
                current_tokens += sent_tokens

            if current_chunk:
                chunks.append(
                    {
                        "content": " ".join(current_chunk),
                        "chapter_title": chapter.title,
                        "chapter_number": chapter.chapter_number,
                        "start_time": chapter.start_time,
                        "source_file": segmented.source_file,
                    }
                )

    return chunks
