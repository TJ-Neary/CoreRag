import logging
import shutil
from pathlib import Path
from src.staging import get_item, update_item, load_manifest, save_manifest
from src.archiver import archive_to_target
from src.exporter import export_to_vault

def execute_approved_item(item_id: str):
    """
    Finalizes an item:
    1. Renames original file if needed.
    2. Archives to the approved folder.
    3. Exports to Vault.
    4. Updates Status to 'completed'.
    """
    item = get_item(item_id)
    if not item:
        logging.error(f"Item {item_id} not found.")
        return False
    
    if item["status"] != "approved":
        logging.error(f"Item {item_id} is not approved (Status: {item['status']})")
        return False

    original_path = Path(item["original_path"])
    if not original_path.exists():
        logging.error(f"Original file missing: {original_path}")
        update_item(item_id, {"status": "error", "error": "File missing"})
        return False

    proposed = item["proposed"]
    target_filename = proposed.get("filename")
    target_folder = proposed.get("target_folder") # e.g. "Financial/2024"

    # Rename if needed (locally before move)
    # Actually, archiver takes the file_path and uses its .name.
    # So we should rename the file on disk OR pass the target name to archiver?
    # Archiver uses `file_path.name`.
    # Let's rename the file in place first if the name changed.
    
    current_path = original_path
    if target_filename:
        # Check if suffix is missing in target_filename (user might omit .pdf)
        if not Path(target_filename).suffix:
            target_filename += original_path.suffix
            
        if target_filename != original_path.name:
            new_path = original_path.with_name(target_filename)
            try:
                original_path.rename(new_path)
                current_path = new_path
                logging.info(f"Renamed {original_path.name} -> {target_filename}")
            except Exception as e:
                logging.error(f"Failed to rename file: {e}")
                ## Keep going with old name? Or fail? Fail is safer.
                update_item(item_id, {"status": "error", "error": f"Rename failed: {e}"})
                return False

    try:
        # Move to Archive
        # Helper: if target_folder is empty, use default logic? 
        # The GUI should ensure target_folder is populated (e.g. defaulting to AI guess).
        # We'll assume target_folder is valid relative path.
        if not target_folder:
             # Fallback if UI sent empty
             target_folder = f"{item['metadata'].get('category')}/{item['metadata'].get('year')}"

        archive_to_target(current_path, target_folder)
        
        # Export to Vault
        # We use the NEW metadata from 'proposed' (user edits to tags/year etc)
        # We need to construct a 'metadata' dict that exporter expects.
        # Exporter uses: year, type, category, summary.
        # The 'proposed' dict has filename, category, year, type.
        # We merge original metadata with proposed updates.
        
        final_metadata = item["metadata"].copy()
        final_metadata.update({
            "category": proposed.get("category"),
            "year": proposed.get("year"),
            "type": proposed.get("type")
        })
        
        export_to_vault(item["redacted_text"], final_metadata, current_path.name)
        
        # Update Staging Status
        update_item(item_id, {"status": "completed"})
        return True

    except Exception as e:
        logging.error(f"Execution failed for {item_id}: {e}")
        update_item(item_id, {"status": "error", "error": str(e)})
        return False
