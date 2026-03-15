#!/usr/bin/env python3
"""
One-off script to drop any unique index on job_id only in ApplicationsCollection.
Run from project root: python fix_applications_index.py
After running, restart the app so it can recreate the correct indexes.
"""
import os
import sys

# Ensure project root is on path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.chdir(os.path.dirname(os.path.abspath(__file__)))

from database import get_applications_collection

def main():
    apps = get_applications_collection()
    indexes = apps.index_information()
    dropped = []
    for name, info in indexes.items():
        if name == "_id_":
            continue
        key = info.get("key")
        if key is None:
            continue
        key_names = list(key.keys()) if isinstance(key, dict) else [k[0] for k in list(key)]
        is_unique = info.get("unique", False)
        print(f"Index: {name!r}  key={key_names}  unique={is_unique}")
        if is_unique and key_names == ["job_id"]:
            try:
                apps.drop_index(name)
                dropped.append(name)
                print(f"  -> Dropped {name!r}")
            except Exception as e:
                print(f"  -> Failed to drop: {e}")
        elif name == "job_id_1" and is_unique:
            try:
                apps.drop_index(name)
                dropped.append(name)
                print(f"  -> Dropped {name!r} (by name)")
            except Exception as e:
                print(f"  -> Failed to drop: {e}")
        elif is_unique and "applicant_id" in key_names:
            try:
                apps.drop_index(name)
                dropped.append(name)
                print(f"  -> Dropped {name!r} (app uses user_id, not applicant_id; this index was blocking)")
            except Exception as e:
                print(f"  -> Failed to drop: {e}")
    if dropped:
        print(f"\nDropped {len(dropped)} index(es). Restart the app so it can recreate the correct (user_id, job_id) unique index.")
    else:
        print("\nNo unique job_id-only index found. If you still get DuplicateKeyError, paste the output above and the exact error.")


if __name__ == "__main__":
    main()
