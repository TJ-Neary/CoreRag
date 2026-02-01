import shutil
import yaml
import os
import sys
from pathlib import Path
from unittest.mock import patch

# Setup Dummy Env
os.environ["INBOX_PATH"] = "/dummy/inbox"
os.environ["VAULT_PATH"] = "/dummy/vault"
os.environ["ARCHIVE_PATH"] = "/dummy/archive"
os.environ["GOOGLE_API_KEY"] = "dummy_key"

sys.path.append(os.getcwd())

TEMP_ROOT = Path("temp_test_rules")
ARCHIVE = TEMP_ROOT / "Archive"
INBOX = TEMP_ROOT / "Inbox"
RULES_FILE = Path("sorting_rules.yaml")

def setup():
    if TEMP_ROOT.exists():
        shutil.rmtree(TEMP_ROOT)
    INBOX.mkdir(parents=True)
    ARCHIVE.mkdir(parents=True)
    
    # Create valid rules
    rules = {
        "rules": [
            {
                "name": "Test Rule",
                "condition": {"type": "filename", "pattern": "special"},
                "target": "Special/Folder"
            }
        ]
    }
    with open(RULES_FILE, "w") as f:
        yaml.dump(rules, f)

def cleanup():
    if RULES_FILE.exists():
        RULES_FILE.unlink()
    if TEMP_ROOT.exists():
        shutil.rmtree(TEMP_ROOT)

def test_sorting_rules():
    print("--- Testing Sorting Rules ---")
    setup()
    
    import src.archiver

    # Test Case 1: File matching rule ("special_doc.txt")
    file1 = INBOX / "special_doc.txt"
    file1.touch()
    
    with patch("src.archiver.ARCHIVE_PATH", ARCHIVE):
        # Metadata says "General", but Rule says "Special"
        metadata = {"category": "General", "year": "2024"}
        
        print(f"Archiving {file1.name} (Should trigger User Rule)...")
        src.archiver.archive_original(file1, metadata)
        
        expected = ARCHIVE / "Special/Folder" / "special_doc.txt"
        if expected.exists():
            print("✅ PASSED: User Rule overrode AI classification.")
        else:
            print("❌ FAILED: User Rule ignored.")
            
    # Test Case 2: File NOT matching rule ("normal.txt")
    file2 = INBOX / "normal.txt"
    file2.touch()
    
    with patch("src.archiver.ARCHIVE_PATH", ARCHIVE):
        # Should follow AI metadata
        metadata = {"category": "General", "year": "2024"}
        
        print(f"Archiving {file2.name} (Should follow AI)...")
        src.archiver.archive_original(file2, metadata)
        
        expected = ARCHIVE / "General" / "2024" / "normal.txt"
        if expected.exists():
            print("✅ PASSED: AI Classification used for non-matching file.")
        else:
            print("❌ FAILED: AI Classification failed.")

    cleanup()
    print("--- Test Complete ---")

if __name__ == "__main__":
    test_sorting_rules()
