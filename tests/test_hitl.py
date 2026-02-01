import os
import sys
import shutil
import json
from pathlib import Path
from unittest.mock import patch
from fastapi.testclient import TestClient

# Mock Env
os.environ["INBOX_PATH"] = "/dummy/inbox"
os.environ["VAULT_PATH"] = "/dummy/vault"
os.environ["ARCHIVE_PATH"] = "/dummy/archive"
os.environ["GOOGLE_API_KEY"] = "dummy_key"

sys.path.append(os.getcwd())

TEMP_ROOT = Path("temp_test_hitl")
INBOX = TEMP_ROOT / "Inbox"
VAULT = TEMP_ROOT / "Vault"
ARCHIVE = TEMP_ROOT / "Archive"
MANIFEST = Path("staging_manifest.json")

def setup_env():
    if TEMP_ROOT.exists():
        shutil.rmtree(TEMP_ROOT)
    INBOX.mkdir(parents=True)
    VAULT.mkdir(parents=True)
    ARCHIVE.mkdir(parents=True)
    if MANIFEST.exists():
        MANIFEST.unlink()

def test_hitl_api():
    print("--- Starting HITL API Test ---")
    setup_env()
    
    # Needs to import server after env setup/mocking if it reads env at top level?
    # src/server.py imports src.staging which expects env? No, staging just reads JSON.
    # executor imports archiver which expects env.
    
    # We must patch constants in modules before functionality is used.
    # But for TestClient, we import 'app' from server.
    
    from src.server import app
    import src.staging
    import src.archiver
    import src.executor
    import src.exporter

    client = TestClient(app)

    # 1. Create a Staged Item directly
    test_file = INBOX / "raw_report.txt"
    test_file.write_text("Confidential Data")
    
    print("Adding item to staging...")
    with patch("src.staging.STAGING_MANIFEST_PATH", MANIFEST):
        item_id = src.staging.add_to_staging(
            original_path=test_file,
            metadata={"category": "Work", "year": "2024", "is_sensitive": True},
            redacted_text="[REDACTED] Data",
            suggested_filename="CUI_raw_report"
        )
    
        # 2. Query Queue
        print("GET /api/queue")
        response = client.get("/api/queue")
        assert response.status_code == 200
        data = response.json()
        assert item_id in data
        assert data[item_id]["proposed"]["filename"] == "CUI_raw_report"
        
        # 3. Update Item (User changes name)
        print("POST /api/update")
        new_name = "Approved_Report.txt"
        client.post(f"/api/update/{item_id}", json={
            "proposed": {
                "filename": new_name,
                "category": "Work",
                "year": "2024",
                # The Dashboard logic sends 'target_folder'. Let's simulate that if we want,
                # or check if executor handles it.
                "target_folder": "Work/2024"
            }
        })
        
        # Verify update in manifest
        updated_item = src.staging.get_item(item_id)
        assert updated_item["proposed"]["filename"] == new_name
        
        # 4. Approve Item
        print("POST /api/approve")
        
        # We need to mock the Archiver/Exporter paths during execution
        with patch("src.archiver.ARCHIVE_PATH", ARCHIVE), \
             patch("src.exporter.VAULT_PATH", VAULT):
             
             # The endpoint runs background task. TestClient waits for it? 
             # FastAPI TestClient runs background tasks synchronously usually.
             response = client.post(f"/api/approve/{item_id}")
             assert response.status_code == 200
             
        # 5. Verify Execution
        print("Verifying outcome...")
        
        # Check Archive (Should use new name)
        # target_folder was "Work/2024"
        expected_archive = ARCHIVE / "Work" / "2024" / "Approved_Report.txt"
        if expected_archive.exists():
            print(f"✅ PASSED: File moved and renamed to {expected_archive}")
        else:
            print(f"❌ FAILED: File missing. Archive contents:")
            for p in ARCHIVE.rglob("*"): print(f"  - {p}")

        # Check Vault
        vault_files = list((VAULT / "Ingested").glob("*.md"))
        if len(vault_files) >= 1:
            note = vault_files[0]
            print(f"✅ PASSED: Vault note created: {note.name}")
            if "Approved_Report" in note.name or "2024 - Doc - Approved_Report" in note.name: # Logic depends on exporter
                 pass
        else:
             print("❌ FAILED: Vault note missing.")

    print("--- Test Complete ---")

if __name__ == "__main__":
    test_hitl_api()
