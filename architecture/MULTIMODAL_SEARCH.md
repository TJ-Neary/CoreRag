# Multi-Modal Search Architecture

> **Status**: ✅ Implemented | See `src/search/, src/multimodal/` for implementation

## Overview

Multi-modal search enables querying across different content types (text, images, audio, video) with a unified interface. Users can search with text and find relevant images, or search with an image and find related documents.

---

## Embedding Strategy

### Unified Vector Space

All content types are embedded into a shared 768-dimensional vector space using compatible models:

| Content Type | Model | Dimensions | Notes |
|--------------|-------|------------|-------|
| Text | nomic-embed-text-v1.5 | 768 | Primary model |
| Images | nomic-embed-vision-v1.5 | 768 | Same family, compatible |
| Audio | Text of transcription | 768 | Via mlx-whisper → text embed |
| Video | Keyframes + transcript | 768 | Combined approach |

### Why Same-Family Models Matter

- Models trained together share semantic space
- "A photo of a dog" (text) is near actual dog photos (image)
- Enables true cross-modal search

---

## Content Processing

### Text Documents

```
Document → Chunks → Text Embeddings
                        ↓
                  Vector DB (text table)
```

### Images

```
Image → Description (BLIP/LLaVA) → Text Embedding
    ↓
    Visual Embedding (nomic-vision)
    ↓
Vector DB (image table) with both embeddings
```

### Audio

```
Audio → Whisper Transcription → Text Chunks → Text Embeddings
                                                    ↓
                                            Vector DB (audio table)
```

### Video

```
Video → Extract Audio → Transcription → Text Embedding
    ↓
    Keyframe Extraction → Visual Embedding
    ↓
Vector DB (video table) with timestamp alignment
```

---

## Search Modes

### Mode 1: Text → All Content

User types: "sunset over mountains"

```python
query_embedding = embed_text("sunset over mountains")

results = search_all_tables(
    embedding=query_embedding,
    tables=["text", "images", "audio", "video"],
    limit=20
)
```

Returns:
- Text documents mentioning sunsets
- Photos of mountain sunsets
- Audio recordings describing scenery
- Video clips of mountain views

### Mode 2: Image → Similar Content

User uploads an image of a flowchart

```python
image_embedding = embed_image(uploaded_image)

# Find similar images
similar_images = search_table("images", image_embedding)

# Find related text (using image description)
description = describe_image(uploaded_image)
text_embedding = embed_text(description)
related_docs = search_table("text", text_embedding)
```

### Mode 3: Hybrid Query

User types: "diagrams like this" + uploads image

```python
text_embedding = embed_text("diagrams like this")
image_embedding = embed_image(uploaded_image)

# Weighted combination
combined = (text_embedding * 0.3) + (image_embedding * 0.7)
results = search_all_tables(combined)
```

---

## Database Schema

### Unified Metadata Table

```sql
CREATE TABLE content_index (
    id TEXT PRIMARY KEY,
    content_type TEXT,  -- "text", "image", "audio", "video"
    source_file TEXT,
    embedding VECTOR(768),
    created_at TIMESTAMP,
    metadata JSON
);
```

### Type-Specific Tables

```python
# Text chunks
class TextChunk:
    id: str
    content: str
    embedding: Vector[768]
    document_id: str
    position: int

# Image records
class ImageRecord:
    id: str
    file_path: str
    text_embedding: Vector[768]   # From description
    visual_embedding: Vector[768]  # From image itself
    description: str
    dimensions: tuple

# Audio segments
class AudioSegment:
    id: str
    file_path: str
    embedding: Vector[768]
    transcript: str
    start_time: float
    end_time: float
    speaker: Optional[str]

# Video segments
class VideoSegment:
    id: str
    file_path: str
    text_embedding: Vector[768]
    visual_embedding: Vector[768]
    transcript: str
    keyframe_path: str
    start_time: float
    end_time: float
```

---

## Result Merging

### Score Normalization

Different tables may have different score distributions:

```python
def normalize_scores(results_by_table):
    """Normalize scores to 0-1 range per table, then merge."""
    normalized = []

    for table, results in results_by_table.items():
        if not results:
            continue

        scores = [r.score for r in results]
        min_s, max_s = min(scores), max(scores)

        for result in results:
            norm_score = (result.score - min_s) / (max_s - min_s + 1e-6)
            result.normalized_score = norm_score
            result.source_table = table
            normalized.append(result)

    return sorted(normalized, key=lambda r: r.normalized_score, reverse=True)
```

### Type Weighting

User preferences for result types:

```python
TYPE_WEIGHTS = {
    "text": 1.0,      # Default preference
    "image": 0.9,
    "audio": 0.85,
    "video": 0.8
}

def apply_type_weights(results):
    for r in results:
        r.final_score = r.normalized_score * TYPE_WEIGHTS[r.content_type]
    return sorted(results, key=lambda r: r.final_score, reverse=True)
```

---

## Cross-Modal Links

### Automatic Linking

When processing, detect cross-modal relationships:

```python
def find_cross_modal_links(document):
    links = []

    # Images referenced in text
    for img_ref in extract_image_references(document.text):
        if img_id := find_image_by_name(img_ref):
            links.append(Link(document.id, img_id, "references"))

    # Audio transcripts matching text
    for audio in find_similar_audio(document.embedding):
        if audio.score > 0.85:
            links.append(Link(document.id, audio.id, "related"))

    return links
```

### Link Types

| Type | Description | Example |
|------|-------------|---------|
| `references` | Explicit reference | Document mentions "see diagram.png" |
| `embedded` | Content embedded | PDF contains images |
| `related` | Semantic similarity | Audio discusses same topic |
| `derivative` | Derived content | Transcript from video |
| `grouped` | Same project/folder | All files in /Project-X/ |

---

## Search Examples

### Example 1: "Meeting notes with diagrams"

```python
results = multimodal_search(
    query="meeting notes with diagrams",
    content_types=["text", "image"],
    require_links=True  # Only results that have cross-links
)
```

### Example 2: "Audio from last week about ML"

```python
results = multimodal_search(
    query="machine learning discussion",
    content_types=["audio"],
    date_range=("2024-01-08", "2024-01-15")
)
```

### Example 3: Visual similarity search

```python
results = visual_search(
    image_path="/path/to/reference.png",
    content_types=["image", "video"],  # Find similar images and video keyframes
    limit=20
)
```

---

## Performance Considerations

### Batch Processing

```python
# Process images in batches for GPU efficiency
BATCH_SIZE = 16

for batch in chunks(images, BATCH_SIZE):
    embeddings = embed_images_batch(batch)  # Single GPU call
    store_embeddings(batch, embeddings)
```

### Caching

- Cache image descriptions (expensive to regenerate)
- Cache visual embeddings (stable unless image changes)
- Cache cross-modal links (updated on content change)

### Index Strategy

```python
# Separate indexes per content type for faster type-filtered search
indexes = {
    "text": lancedb.open("text_index"),
    "image": lancedb.open("image_index"),
    "audio": lancedb.open("audio_index"),
    "video": lancedb.open("video_index"),
    "unified": lancedb.open("unified_index")  # For cross-modal
}
```

---

## Future Enhancements

1. **CLIP-style models**: More advanced image-text alignment
2. **Audio embeddings**: Direct audio embedding without transcription
3. **Video understanding**: Action recognition, scene detection
4. **OCR integration**: Text in images becomes searchable
5. **Diagram understanding**: Flowcharts, architecture diagrams
