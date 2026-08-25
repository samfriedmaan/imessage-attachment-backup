# iMessage Attachment Backup & Organizer

A fast, lightweight macOS utility that backs up all your iMessage attachments and organizes them into clean, human-readable folders named by **Contact Name** or **Group Chat Title**.

Under the hood, it wraps the high-performance [`imessage-exporter`](https://github.com/ReagentX/imessage-exporter) tool and enhances it with smart macOS Contacts integration, multi-handle unification, and duplicate name disambiguation.

---

## Features

- **Organized by Contact Name**: Attachments are automatically sorted into folders named after your contacts (e.g. `John Doe/`, `Mom/`, `Project Team/`) instead of cryptic hashes or phone numbers.
- **Multi-Handle Combining**: If a contact has multiple phone numbers (mobile, work, home) and email addresses, all their attachments are automatically unified into that single person's folder.
- **Smart Disambiguation**: Prevents collisions between different people who share the same First & Last name by disambiguating using their organization, note, or primary phone number (e.g. `John Doe (Company A)` vs `John Doe (555-123-4567)`).
- **Clean Group Chat Names**: Strips disambiguation numbers and metadata from group chat titles (e.g. `Book Club - 246` $\rightarrow$ `Book Club`).
- **Directory & Live Photo Support**: Properly transfers directories, Live Photos, stickers, and audio packages without errors.
- **Two Modes of Operation**:
  - **Full Automated Backup**: Exports and organizes all iMessage attachments directly from your Mac in one command.
  - **Organize Existing Export**: Instantly organizes an existing `imessage-exporter` export directory in seconds.
- **Zero Python Dependencies**: Built entirely with Python 3's standard library (no `pip install` required).

---

## Prerequisites

1. **macOS** (utilizes native macOS Contacts / AppleScript integration).
2. **`imessage-exporter`**:
   Install via [Homebrew](https://brew.sh):
   ```bash
   brew install imessage-exporter
   ```
3. **Full Disk Access**:
   Your terminal app (Terminal, iTerm2, etc.) needs Full Disk Access to read the local Messages database.
   - Go to **System Settings > Privacy & Security > Full Disk Access**.
   - Enable your terminal application.

---

## Quick Start

Clone or download this repository, then run:

```bash
python3 backup-attachments.py
```

This will:
1. Export all your iMessage attachments to a temporary workspace using `imessage-exporter`.
2. Query macOS Contacts to resolve phone numbers and emails to clean names.
3. Organize all attachments into `~/<YYYY-MM-DD>_iMessage_Attachments/<Contact Name>/`.
4. Automatically clean up intermediate transcript files.

---

## Usage & Options

```text
usage: backup-attachments.py [-h] [-s SOURCE] [-o OUTPUT]
                                     [-m {copy,move}] [-c {clone,basic,full}]
                                     [-f {txt,html}] [--keep-temp]

Backup and organize iMessage attachments into folders by Contact Name.

options:
  -h, --help            Show this help message and exit.
  -s, --source SOURCE   Path to an existing imessage-exporter export folder
                        (e.g. ~/imessage_export). If omitted, runs a fresh export.
  -o, --output OUTPUT   Destination directory for organized attachments
                        (default: ~/<YYYY-MM-DD>_iMessage_Attachments).
  -m, --mode {copy,move}
                        Whether to 'copy' or 'move' attachments when organizing
                        an existing export directory (default: copy).
  -c, --copy-method {clone,basic,full}
                        Attachment copy method for imessage-exporter:
                        - clone: copy original files without conversion (default).
                        - basic: convert HEIC images to JPEG.
                        - full: convert HEIC to JPEG, CAF to MP4, MOV to MP4.
  -f, --format {txt,html}
                        Intermediate transcript format (default: txt).
  --keep-temp           Keep intermediate transcript files when running a fresh export.
```

---

## Examples

### 1. Run a fresh backup to a custom folder
```bash
python3 backup-attachments.py -o ~/Desktop/My_iMessage_Photos
```

### 2. Convert HEIC images to JPEG automatically during export
```bash
python3 backup-attachments.py -c basic
```

### 3. Organize an existing export folder (saves disk space with `move`)
If you have already run `imessage-exporter` previously:
```bash
python3 backup-attachments.py -s ~/imessage_export -m move -o ~/Organized_Attachments
```

---

## How It Works

1. **Extraction**: Calls `imessage-exporter` to extract all attachments and conversation transcripts from `~/Library/Messages/chat.db`.
2. **Contact Mapping**: Queries the macOS Address Book via fast JXA batch query to create an in-memory lookup table of unique contact cards, handles (phone numbers & emails), and organizations.
3. **Parsing & Resolution**:
   - Matches 1-on-1 conversations to their corresponding contact card.
   - Names group chats with their custom title or a clean list of participants.
   - Strips edit timestamps, reactions, and internal ID suffixes.
4. **Organization**: Moves/copies all files into `<Output_Dir>/<Contact_Name>/<filename>`, deduplicating identical files and handling filename collisions safely.

---

## License

MIT License. Feel free to use, modify, and distribute!
