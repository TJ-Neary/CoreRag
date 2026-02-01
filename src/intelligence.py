import google.generativeai as genai
import json
import logging
import os
import re
from src.config import GOOGLE_API_KEY

# Configure Gemini
if GOOGLE_API_KEY:
    genai.configure(api_key=GOOGLE_API_KEY)
else:
    logging.warning("No GOOGLE_API_KEY found. Intelligence features will be disabled.")

def analyze_document(text: str):
    """
    Analyzes text to extract metadata and create a redacted version.
    Returns: (metadata_dict, redacted_text_str)
    """
    if not GOOGLE_API_KEY or not text.strip():
        # Fallback if no key or empty text
        return {
            "category": "Unsorted",
            "year": "Unknown",
            "type": "Document",
            "summary": "No AI analysis performed."
        }, text

    try:
        model = genai.GenerativeModel('gemini-1.5-pro-latest')
        
        prompt = f"""
        You are a Privacy and Archival Assistant. Your task is to process the following document text.
        
        1. **Redaction**: Replace any PII (names, SSNs, phones, emails, addresses, accounts) with [REDACTED].
        2. **Classification**:
           - Category: High level (Medical, Financial, Legal, Personal, Work).
           - Year: primary year (YYYY).
           - Type: Specific type (Statement, Receipt, Contract, Prescription).
        3. **Naming**: Propose a concise, descriptive filename based on content (e.g., "Medical_Invoice_Jan.pdf"). Do NOT include extension.
        4. **Sensitivity**: Set is_sensitive to true if ANY PII was found/redacted.
        5. **Summary**: Brief summary.

        Output ONLY valid JSON:
        {{
            "metadata": {{
                "category": "Category",
                "year": "YYYY",
                "type": "Type",
                "summary": "...",
                "suggested_name": "filename_without_ext",
                "is_sensitive": true/false
            }},
            "redacted_text": "..."
        }}

        Document Text (Truncated):
        {text[:50000]}
        """

        response = model.generate_content(prompt)
        
        # Parse JSON from response
        cleaned_response = _clean_json_markdown(response.text)
        data = json.loads(cleaned_response)
        
        return data.get("metadata", {}), data.get("redacted_text", "")

    except Exception as e:
        logging.error(f"Intelligence Analysis Failed: {e}")
        # Fallback on failure
        return {
            "category": "Error",
            "year": "Unknown", 
            "type": "Error",
            "summary": "Analysis failed.",
            "suggested_name": "unknown_file",
            "is_sensitive": False
        }, text

def _clean_json_markdown(text: str) -> str:
    """Removes markdown code block formatting to extract raw JSON."""
    pattern = r"```json\s*(.*?)\s*```"
    match = re.search(pattern, text, re.DOTALL)
    if match:
        return match.group(1)
    return text.strip()
