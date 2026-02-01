# Your Setup Tasks

These are the tasks that require your manual action - they can't be automated by Antigravity agents.

---

## 1. Install Dependencies

### 1.1 Presidio (PII Detection)

```bash
# Install Presidio analyzer
pip install presidio-analyzer

# Download the spaCy NER model (required for name/location detection)
python -m spacy download en_core_web_lg
```

**Verify installation:**
```python
from presidio_analyzer import AnalyzerEngine
analyzer = AnalyzerEngine()
results = analyzer.analyze(text="John Smith lives in New York", language="en")
print(results)  # Should show PERSON and LOCATION entities
```

### 1.2 Verify Vision.framework (OCR)

Apple Vision.framework requires:
- macOS 10.15 (Catalina) or later
- Xcode Command Line Tools installed

```bash
# Check macOS version
sw_vers

# Install Xcode CLI tools if needed
xcode-select --install
```

The `VisionOCR` class in `src/ocr/vision_ocr.py` uses PyObjC to access Vision.framework directly.

---

## 2. Remote Access (Tailscale)

### 2.1 Configure Server Binding

Edit your Open WebUI or MCP server config to listen on all interfaces:

```bash
# Instead of:
HOST=127.0.0.1

# Use:
HOST=0.0.0.0
# Or your Tailscale IP:
HOST=100.x.x.x
```

### 2.2 Enable MagicDNS

1. Go to [Tailscale Admin Console](https://login.tailscale.com/admin/dns)
2. Enable **MagicDNS**
3. Note your machine name (e.g., `m4-max`)

### 2.3 Test Access

From your phone or another device on Tailscale:
```bash
curl http://m4-max:3000/health
# Or whatever port your server runs on
```

---

## 3. Web Clipper Setup

### 3.1 Install Browser Extension

Choose one:
- **MarkDownload** (Chrome/Firefox) - Simple, saves as Markdown
- **Omnivore** - Full-featured read-later with API

### 3.2 Configure Output Directory

Set the download directory to your PKM watch folder:
```
~/Documents/PKM_Input/
```

### 3.3 Enable Frontmatter

Configure the extension to include metadata:
```yaml
---
source_url: https://example.com/article
date: 2026-01-31
title: Article Title
---
```

This ensures the ingestion pipeline captures provenance.

---

## 4. Golden Set Creation

The Golden Set is your regression test suite - it ensures search quality doesn't degrade when you make changes.

### 4.1 Location

```
tests/golden_set.yaml
```

A template with example cases is already created. You need to populate it with YOUR queries and expected files.

### 4.2 Format

```yaml
test_cases:
  # Each test case has a query and expected file(s)
  - id: "unique_id"
    query: "Your natural language question"
    expected_files:
      - "path/to/expected/file.md"
    category: "category_name"  # Optional: for grouping
    notes: "Why this query should find this file"  # Optional
```

### 4.3 How to Create Good Test Cases

**Step 1: Start with real queries you've asked**
Think about questions you've actually searched for in your knowledge base.

**Step 2: Cover different query types**

| Type | Example Query | Why It Matters |
|------|---------------|----------------|
| **Factual** | "What is our vacation policy?" | Tests exact match retrieval |
| **Conceptual** | "How does authentication work?" | Tests semantic understanding |
| **Temporal** | "Meeting notes from last week" | Tests time-aware retrieval |
| **Multi-hop** | "Projects John worked on" | Tests entity linking |
| **Jargon** | "Configure k8s ingress" | Tests technical vocabulary |

**Step 3: Include edge cases**

```yaml
# Synonym handling
- id: "auth_synonyms"
  query: "login security"
  expected_files:
    - "docs/authentication.md"  # Uses "authentication" not "login"

# Abbreviation handling
- id: "abbreviations"
  query: "ML pipeline"
  expected_files:
    - "projects/machine-learning-pipeline.md"

# Negation (harder)
- id: "negation"
  query: "meetings without action items"
  expected_files:
    - "meetings/brainstorm-2026-01.md"  # Informal meeting
```

### 4.4 Recommended Test Set Size

| Stage | Test Cases | Purpose |
|-------|------------|---------|
| **Initial** | 20-30 | Basic coverage |
| **Production** | 50-100 | Comprehensive regression |
| **Mature** | 100+ | Full quality assurance |

### 4.5 Running the Tests

```bash
# Run all golden set tests
pytest tests/test_golden_set.py -v

# Run with coverage report
pytest tests/test_golden_set.py -v --tb=short

# Run specific category
pytest tests/test_golden_set.py -v -k "factual"
```

### 4.6 Example Golden Set (Template)

Here's a starter set you can customize:

```yaml
# tests/golden_set.yaml
version: "1.0"
embedding_model: "nomic-embed-text-v1.5"
created: "2026-01-31"
author: "TJ"

test_cases:
  # === FACTUAL RETRIEVAL ===
  - id: "fact_001"
    query: "What are the project deadlines for Q1?"
    expected_files:
      - "projects/q1-roadmap.md"
    category: "factual"

  - id: "fact_002"
    query: "Contact information for vendors"
    expected_files:
      - "contacts/vendors.md"
    category: "factual"

  # === CONCEPTUAL/HOW-TO ===
  - id: "concept_001"
    query: "How do I set up the development environment?"
    expected_files:
      - "docs/dev-setup.md"
    category: "conceptual"

  - id: "concept_002"
    query: "Best practices for code review"
    expected_files:
      - "docs/code-review-guide.md"
    category: "conceptual"

  # === TEMPORAL ===
  - id: "temporal_001"
    query: "Recent meeting notes"
    expected_files:
      - "meetings/2026-01-30-standup.md"
      - "meetings/2026-01-29-planning.md"
    category: "temporal"

  # === TECHNICAL/JARGON ===
  - id: "tech_001"
    query: "API authentication flow"
    expected_files:
      - "docs/api/authentication.md"
    category: "technical"

  - id: "tech_002"
    query: "Database migration scripts"
    expected_files:
      - "scripts/migrations/README.md"
    category: "technical"

  # === CROSS-REFERENCE ===
  - id: "xref_001"
    query: "Tasks assigned to me"
    expected_files:
      - "tasks/tj-tasks.md"
    category: "personal"

  # === EDGE CASES ===
  - id: "edge_001"
    query: "TL;DR of the architecture"
    expected_files:
      - "architecture/overview.md"
    category: "edge"
    notes: "Tests abbreviation handling"

  - id: "edge_002"
    query: "stuff about ML models"
    expected_files:
      - "projects/machine-learning/models.md"
    category: "edge"
    notes: "Tests informal query language"
```

---

## 5. Checklist

Use this to track your progress:

```
[ ] Install Presidio: pip install presidio-analyzer
[ ] Download spaCy model: python -m spacy download en_core_web_lg
[ ] Verify macOS version for Vision.framework
[ ] Configure Tailscale server binding
[ ] Enable MagicDNS in Tailscale admin
[ ] Test remote access from phone
[ ] Install MarkDownload or Omnivore extension
[ ] Configure extension output directory
[ ] Enable frontmatter in extension
[ ] Create 20+ Golden Set test cases
[ ] Run golden set tests to verify baseline
```

---

## 6. Verification Commands

After completing setup, run these to verify everything works:

```bash
# Test Presidio
python -c "from presidio_analyzer import AnalyzerEngine; print('Presidio OK')"

# Test Vision OCR
python -c "from src.ocr.vision_ocr import VisionOCR; print('Vision OK')"

# Test Golden Set
pytest tests/test_golden_set.py -v --tb=short

# Test Memory Management
python -c "from src.utils.safe_processor import print_status; print_status()"

# Test Privacy Scanner
python -c "from src.utils.privacy_audit import check_privacy; print(check_privacy('John Smith, SSN 123-45-6789'))"
```

---

*Last Updated: 2026-01-31*
