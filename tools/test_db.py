import os
import sys
from pathlib import Path

# Add the src directory to sys.path so we can import the fabulor package
sys.path.insert(0, str(Path(__file__).parent / "src"))

from fabulor.db import LibraryDB

def main():
    # 1. Setup temporary database
    test_db_path = Path("test_library.db")
    if test_db_path.exists():
        test_db_path.unlink()

    print(f"--- Starting LibraryDB Tests (using {test_db_path}) ---")
    db = LibraryDB(test_db_path)

    # 2. Test Scan Locations
    print("Testing Scan Locations...")
    loc1 = "/home/pryme/audiobooks/fantasy"
    loc2 = "/home/pryme/audiobooks/sci-fi"
    
    db.add_scan_location(loc1)
    db.add_scan_location(loc2)
    locations = db.get_scan_locations()
    assert loc1 in locations and loc2 in locations, "Failed to retrieve added scan locations"
    print(f"  ✓ Added and retrieved: {len(locations)} locations")
    
    db.remove_scan_location(loc1)
    locations = db.get_scan_locations()
    assert loc1 not in locations, "Failed to remove scan location"
    assert loc2 in locations, "Incorrectly removed the wrong scan location"
    print("  ✓ Removed location successfully")

    # 3. Test Book Upsert and Verification
    print("\nTesting Book Upsert & Retrieval...")
    book1 = {
        "path": "/home/pryme/audiobooks/fantasy/WayOfKings.m4b",
        "title": "The Way of Kings",
        "author": "Brandon Sanderson",
        "narrator": "Michael Kramer",
        "duration": 172800.5,
        "cover_path": "/home/pryme/.cache/fabulor/wok.jpg"
    }
    db.upsert_book(book1)
    retrieved = db.get_book(book1["path"])
    
    assert retrieved is not None, "Book not found after upsert"
    assert retrieved["title"] == book1["title"]
    assert retrieved["author"] == book1["author"]
    assert retrieved["narrator"] == book1["narrator"]
    assert retrieved["duration"] == book1["duration"]
    assert retrieved["cover_path"] == book1["cover_path"]
    assert retrieved["date_added"] is not None
    assert retrieved["last_played"] is None
    print("  ✓ Initial upsert verification: All fields match")

    # 4. Test Metadata Update (Conflict resolution)
    print("Testing Metadata Update...")
    book1["narrator"] = "Michael Kramer & Kate Reading" # Changed metadata
    db.upsert_book(book1)
    updated = db.get_book(book1["path"])
    assert updated["narrator"] == "Michael Kramer & Kate Reading", "Narrator did not update on conflict"
    assert updated["id"] == retrieved["id"], "Database ID changed on update (should be stable)"
    print("  ✓ Update verification: Narrator changed, ID remained stable")

    # 5. Test Last Played Update
    print("Testing Last Played Update...")
    db.update_last_played(book1["path"])
    played = db.get_book(book1["path"])
    assert played["last_played"] is not None, "last_played timestamp was not set"
    print(f"  ✓ Last played updated: {played['last_played']}")

    # 6. Test Sorting with Multiple Books
    print("\nTesting get_all_books sorting...")
    # Book A: Title 'A...', Author 'Z...'
    db.upsert_book({
        "path": "path_a",
        "title": "A Beautiful Mystery",
        "author": "Zebediah Jones",
        "narrator": "Narrator X",
        "duration": 100.0,
        "cover_path": ""
    })
    # Book C: Title 'C...', Author 'A...'
    db.upsert_book({
        "path": "path_c",
        "title": "Children of Time",
        "author": "Adrian Tchaikovsky",
        "narrator": "Narrator Y",
        "duration": 200.0,
        "cover_path": ""
    })

    # Verify Sort by Title
    by_title = db.get_all_books(sort_by="title")
    titles = [b["title"] for b in by_title]
    assert titles == sorted(titles), f"Title sorting failed: {titles}"
    print(f"  ✓ Alphabetical Title Sort: {titles}")

    # Verify Sort by Author
    by_author = db.get_all_books(sort_by="author")
    authors = [b["author"] for b in by_author]
    assert authors == sorted(authors), f"Author sorting failed: {authors}"
    print(f"  ✓ Alphabetical Author Sort: {authors}")

    # Final Cleanup
    if test_db_path.exists():
        test_db_path.unlink()
    print("\n--- All LibraryDB tests passed successfully! ---")

if __name__ == "__main__":
    main()