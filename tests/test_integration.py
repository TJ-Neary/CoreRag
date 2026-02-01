import os
import sys
import shutil
from pathlib import Path
from unittest.mock import patch

# 1. Setup Dummy Env Vars BEFORE importing src modules
os.environ["INBOX_PATH"] = "/dummy/inbox"
os.environ["VAULT_PATH"] = "/dummy/vault"
os.environ["ARCHIVE_PATH"] = "/dummy/archive"
os.environ["GOOGLE_API_KEY"] = "dummy_key"

sys.path.append(os.getcwd())

TEMP_ROOT = Path("temp_test_env")
INBOX = TEMP_ROOT / "Inbox"
VAULT = TEMP_ROOT / "Vault"
ARCHIVE = TEMP_ROOT / "Archive"

def setup_env():
    if TEMP_ROOT.exists():
        shutil.rmtree(TEMP_ROOT)
    INBOX.mkdir(parents=True)
    VAULT.mkdir(parents=True)
    ARCHIVE.mkdir(parents=True)

def test_integration():
    print("--- Starting Integration Test ---")
    setup_env()
    
    test_file = INBOX / "invoice_2024.txt"
    test_file.write_text("Bill to: John Smith. Amount: $500.")
    print(f"Created test file at: {test_file}")

    import src.archiver
    import src.exporter
    import src.processor

    # Patch 'src.processor.analyze_document' because src.processor imports it directly
    with patch("src.archiver.ARCHIVE_PATH", ARCHIVE), \
         patch("src.exporter.VAULT_PATH", VAULT), \
         patch("src.processor.analyze_document") as mock_ai:
        
        mock_ai.return_value = ({
            "category": "Financial",
            "year": "2024",
            "type": "Invoice",
            "summary": "An invoice for $500."
        }, "Bill to: [REDACTED]. Amount: $500.")

        print("Running process_document...")
        try:
            src.processor.process_document(test_file)
        except Exception as e:
            print(f"❌ Execution Error: {e}")
            import traceback
            traceback.print_exc()

    print("\n--- Verifying Results ---")
    
    expected_archive_path = ARCHIVE / "Financial" / "2024" / "invoice_2024.txt"
    if expected_archive_path.exists():
        print(f"✅ PASSED: File archived to {expected_archive_path}")
    else:
        print(f"❌ FAILED: File not found in archive.")
        for p in ARCHIVE.rglob("*"): print(f"  - {p}")

    vault_files = list((VAULT / "Ingested").glob("*.md"))
    if len(vault_files) == 1:
        note = vault_files[0]
        print(f"✅ PASSED: Vault note created: {note.name}")
        content = note.read_text()
        if "Bill to: [REDACTED]" in content:
            print("✅ PASSED: Redaction verified.")
        else:
            print("❌ FAILED: Redaction missing.")
            print(content)
    else:
        print(f"❌ FAILED: Expected 1 note, found {len(vault_files)}")

    print("\n--- Test Complete ---")

if __name__ == "__main__":
    test_integration()
