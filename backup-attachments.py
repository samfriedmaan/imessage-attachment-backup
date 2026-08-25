#!/usr/bin/env python3
"""
iMessage Attachment Backup & Organizer
Wraps imessage-exporter to organize all attachments into clean folders named by Contact Name.
Combines multiple phone numbers/emails from the same contact card and disambiguates duplicate contact names.
"""

import os
import sys
import re
import json
import shutil
import argparse
import tempfile
import subprocess
from pathlib import Path
from datetime import datetime
from collections import defaultdict


def find_imessage_exporter():
    """Find the imessage-exporter binary path."""
    paths = [
        "/opt/homebrew/bin/imessage-exporter",
        "/usr/local/bin/imessage-exporter",
        shutil.which("imessage-exporter")
    ]
    for p in paths:
        if p and os.path.exists(p) and os.access(p, os.X_OK):
            return p
    return None


def normalize_phone(phone_str):
    """Extract standard digit representation for phone matching."""
    if not phone_str:
        return ""
    digits = re.sub(r"\D", "", str(phone_str))
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    return digits


def format_phone_display(phone_str):
    """Format 10-digit phone number as standard XXX-XXX-XXXX for clean folder naming."""
    digits = normalize_phone(phone_str)
    if len(digits) == 10:
        return f"{digits[:3]}-{digits[3:6]}-{digits[6:]}"
    return str(phone_str).strip()


def load_macos_contacts():
    """
    Load all contacts from macOS Contacts app using fast JXA batch query.
    1. Combines all phone numbers and emails belonging to the same contact card into the same folder.
    2. Disambiguates duplicate contact names (e.g. two separate people named 'John Doe') using organization or primary handle.
    """
    print("Loading macOS Contacts for name resolution...")
    jxa = """
    const app = Application('Contacts');
    const ids = app.people.id();
    const names = app.people.name();
    const orgs = app.people.organization();
    const phones = app.people.phones.value();
    const emails = app.people.emails.value();
    JSON.stringify({ids, names, orgs, phones, emails});
    """
    handle_to_folder = {}
    try:
        res = subprocess.run(
            ["osascript", "-l", "JavaScript", "-e", jxa],
            capture_output=True,
            text=True,
            timeout=25
        )
        if res.returncode == 0:
            data = json.loads(res.stdout)
            ids = data.get("ids", [])
            names = data.get("names", [])
            orgs = data.get("orgs", [])
            phones = data.get("phones", [])
            emails = data.get("emails", [])
            
            # Group contact cards by clean name
            name_to_cards = defaultdict(list)
            for i in range(len(ids)):
                n = (names[i] or "").strip()
                if not n:
                    continue
                o = (orgs[i] if i < len(orgs) else "") or ""
                p_list = phones[i] if i < len(phones) else []
                e_list = emails[i] if i < len(emails) else []
                name_to_cards[n].append({
                    "id": ids[i],
                    "name": n,
                    "org": o.strip() if o else "",
                    "phones": p_list,
                    "emails": e_list
                })
            
            card_to_folder = {}
            for name, cards in name_to_cards.items():
                if len(cards) == 1:
                    card_to_folder[cards[0]["id"]] = name
                else:
                    # Multiple distinct contact cards with identical First & Last name
                    used_folders = set()
                    for c in cards:
                        if c["org"]:
                            folder = f"{name} ({c['org']})"
                        elif c["phones"]:
                            folder = f"{name} ({format_phone_display(c['phones'][0])})"
                        elif c["emails"]:
                            folder = f"{name} ({c['emails'][0]})"
                        else:
                            folder = f"{name} ({c['id'][:8]})"
                        
                        orig_folder = folder
                        idx = 2
                        while folder in used_folders:
                            folder = f"{orig_folder} #{idx}"
                            idx += 1
                        used_folders.add(folder)
                        card_to_folder[c["id"]] = folder
            
            # Map every handle (all phone numbers, all emails) for each card to its resolved folder
            for name, cards in name_to_cards.items():
                for c in cards:
                    folder = card_to_folder[c["id"]]
                    for ph in c["phones"]:
                        d = normalize_phone(ph)
                        if d:
                            handle_to_folder[d] = folder
                            handle_to_folder["1" + d] = folder
                            handle_to_folder["+1" + d] = folder
                    for em in c["emails"]:
                        if em:
                            handle_to_folder[em.strip().lower()] = folder
            
            total_cards = sum(len(v) for v in name_to_cards.values())
            print(f"Successfully loaded {total_cards} contact cards ({len(handle_to_folder)} phone/email lookup keys) from macOS Address Book.")
    except Exception as e:
        print(f"Notice: Could not load Contacts app via AppleScript ({e}). Falling back to transcript metadata.")
    
    return handle_to_folder


def sanitize_folder_name(name, max_len=100):
    """Sanitize and truncate string for safe macOS folder name."""
    if not name:
        return "Unknown"
    # Replace invalid filename characters and colons
    clean = re.sub(r'[/\\:*?"<>|]', "_", name).strip()
    # Strip trailing periods/spaces
    clean = clean.rstrip(". ")
    # Cap length to avoid OS filename length limits (macOS limit is 255 bytes)
    if len(clean) > max_len:
        clean = clean[:max_len].rstrip(". _")
    return clean if clean else "Unknown"


def is_handle_list(name):
    """Check if a conversation identifier is a raw list of handles/numbers."""
    clean = re.sub(r"\s*-\s*\d+$", "", name)
    clean = re.sub(r",\s*and\s+\d+\s+others?$", "", clean, flags=re.IGNORECASE)
    parts = [p.strip() for p in clean.split(",") if p.strip()]
    if not parts:
        return False
    handle_count = 0
    for p in parts:
        digits = re.sub(r"\D", "", p)
        if "@" in p or (digits and len(digits) >= 3 and len(re.sub(r"[\d\s()+-]", "", p)) == 0):
            handle_count += 1
    return handle_count > 0 and (handle_count == len(parts) or handle_count >= 2)


def is_valid_speaker(line):
    """Check if a transcript line is a genuine speaker name."""
    if not line or len(line) > 40:
        return False
    if line == "Me":
        return False
    if line.startswith("attachments/") or line.startswith("http://") or line.startswith("https://") or line.startswith("www."):
        return False
    if ":" in line or "\n" in line or "\r" in line:
        return False
    bad_prefixes = (
        "edited", "laughed", "liked", "loved", "emphasized",
        "disliked", "questioned", "removed", "kept", "sent", "shared"
    )
    if any(line.lower().startswith(b) for b in bad_prefixes):
        return False
    return True


def resolve_contact_name(filename, file_content, contacts_map):
    """
    Resolve a conversation file (e.g. '+15551234567.txt' or 'Project Team - 246.txt')
    to a clean, human-readable Contact or Group Chat name.
    """
    raw_name = filename[:-4] if filename.endswith(".txt") or filename.endswith(".html") else filename
    
    # 1. Named group chat check (e.g. 'Project Team - 246', 'Family Vacation')
    if not is_handle_list(raw_name):
        # Strip trailing - <id>
        m = re.match(r"^(.*?)\s*-\s*\d+$", raw_name)
        return m.group(1) if m else raw_name
    
    # Parse handles from filename
    clean_handles = re.sub(r",\s*and\s+\d+\s+others?$", "", raw_name, flags=re.IGNORECASE)
    handles = [p.strip() for p in clean_handles.split(",") if p.strip()]
    
    # 2. Check single handle in contacts_map directly
    if len(handles) == 1:
        h = handles[0]
        if "@" in h:
            if h.lower() in contacts_map:
                return contacts_map[h.lower()]
        else:
            d = normalize_phone(h)
            if d in contacts_map:
                return contacts_map[d]
    
    # 3. Check transcript for valid speakers
    speakers = []
    lines = file_content.split("\n")
    for i, l in enumerate(lines):
        if re.match(r"^(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d{1,2},\s+\d{4}", l.strip()):
            if i + 1 < len(lines):
                spk = lines[i + 1].strip()
                if is_valid_speaker(spk):
                    # If speaker is a phone number, resolve it
                    spk_d = normalize_phone(spk)
                    if spk_d in contacts_map:
                        spk = contacts_map[spk_d]
                    if spk not in speakers:
                        speakers.append(spk)
    
    if len(speakers) == 1:
        return speakers[0]
    elif len(speakers) > 1:
        extra = f" (+{len(speakers)-3})" if len(speakers) > 3 else ""
        return ", ".join(speakers[:3]) + extra
    
    # 4. If no speakers in transcript, resolve the handles from the filename
    if handles:
        resolved_handles = []
        for h in handles:
            if "@" in h:
                resolved_handles.append(contacts_map.get(h.lower(), h))
            else:
                d = normalize_phone(h)
                resolved_handles.append(contacts_map.get(d, h))
        if len(resolved_handles) == 1:
            return resolved_handles[0]
        extra = f" (+{len(resolved_handles)-3})" if len(resolved_handles) > 3 else ""
        return ", ".join(resolved_handles[:3]) + extra
    
    return raw_name


def parse_attachments_from_file(file_content):
    """Extract relative attachment paths from conversation transcript."""
    matches = re.findall(r"attachments/[^\s\n\r\"'<>]+", file_content)
    return list(dict.fromkeys(matches))  # deduplicate preserving order


def organize_export_directory(source_dir, output_dir, mode="copy", contacts_map=None):
    """Organize all attachments in an imessage-exporter output folder by contact."""
    source_dir = Path(source_dir).expanduser().resolve()
    output_dir = Path(output_dir).expanduser().resolve()
    
    if not source_dir.exists():
        print(f"Error: Source directory does not exist: {source_dir}")
        sys.exit(1)
        
    attachments_dir = source_dir / "attachments"
    if not attachments_dir.exists():
        print(f"Error: No 'attachments' directory found in {source_dir}")
        sys.exit(1)
        
    if contacts_map is None:
        contacts_map = load_macos_contacts()
        
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Find all conversation files (.txt or .html)
    txt_files = list(source_dir.glob("*.txt")) + list(source_dir.glob("*.html"))
    print(f"\nProcessing {len(txt_files)} conversation logs in {source_dir}...")
    
    total_copied = 0
    total_skipped = 0
    errors = 0
    contact_stats = defaultdict(int)
    
    for conv_file in txt_files:
        try:
            with open(conv_file, "r", encoding="utf-8", errors="ignore") as fp:
                content = fp.read()
        except Exception as e:
            print(f"Warning: Could not read {conv_file.name}: {e}")
            continue
            
        att_refs = parse_attachments_from_file(content)
        if not att_refs:
            continue
            
        contact_name = resolve_contact_name(conv_file.name, content, contacts_map)
        folder_name = sanitize_folder_name(contact_name)
        target_folder = output_dir / folder_name
        target_folder.mkdir(parents=True, exist_ok=True)
        
        for rel_att in att_refs:
            src_att_path = source_dir / rel_att
            if not src_att_path.exists():
                continue
                
            dest_file = target_folder / src_att_path.name
            
            # Avoid duplicate copying if file with identical size already exists
            if dest_file.exists():
                try:
                    if dest_file.is_file() and src_att_path.is_file():
                        if dest_file.stat().st_size == src_att_path.stat().st_size:
                            total_skipped += 1
                            contact_stats[folder_name] += 1
                            continue
                except OSError:
                    pass
                
                # Deduplicate filename if different file
                counter = 1
                stem, suffix = src_att_path.stem, src_att_path.suffix
                while dest_file.exists():
                    dest_file = target_folder / f"{stem}_{counter}{suffix}"
                    counter += 1
            
            try:
                if src_att_path.is_dir():
                    if mode == "move":
                        shutil.move(str(src_att_path), str(dest_file))
                    else:
                        shutil.copytree(str(src_att_path), str(dest_file), dirs_exist_ok=True)
                else:
                    if mode == "move":
                        shutil.move(str(src_att_path), str(dest_file))
                    else:
                        shutil.copy2(str(src_att_path), str(dest_file))
                
                total_copied += 1
                contact_stats[folder_name] += 1
            except Exception as e:
                errors += 1
                print(f"Error transferring {src_att_path}: {e}")
                
    print("\n" + "=" * 60)
    print("ORGANIZATION COMPLETE")
    print("=" * 60)
    print(f"Destination:          {output_dir}")
    print(f"Total Folders:        {len(contact_stats)}")
    print(f"Files Copied/Moved:   {total_copied}")
    print(f"Files Skipped (dups): {total_skipped}")
    if errors:
        print(f"Errors:               {errors}")
        
    print("\nTop 20 Contact Folders by Attachment Count:")
    sorted_stats = sorted(contact_stats.items(), key=lambda x: x[1], reverse=True)
    for name, count in sorted_stats[:20]:
        print(f"  {name:40} : {count:5d} files")
        
    return total_copied


def run_full_backup(output_dir, copy_method="clone", format_type="txt", keep_temp=False):
    """Run imessage-exporter to a temporary folder, then organize attachments."""
    exporter = find_imessage_exporter()
    if not exporter:
        print("Error: 'imessage-exporter' was not found on your system.")
        print("Install it with: brew install imessage-exporter")
        sys.exit(1)
        
    output_dir = Path(output_dir).expanduser().resolve()
    temp_export_dir = Path(tempfile.mkdtemp(prefix="imessage_export_"))
    
    print(f"Using imessage-exporter binary: {exporter}")
    print(f"Step 1: Exporting messages and attachments to temporary workspace: {temp_export_dir}...")
    
    cmd = [
        exporter,
        "-f", format_type,
        "-c", copy_method,
        "-o", str(temp_export_dir)
    ]
    
    try:
        process = subprocess.Popen(cmd)
        process.communicate()
        if process.returncode != 0:
            print(f"imessage-exporter exited with code {process.returncode}")
            sys.exit(process.returncode)
    except Exception as e:
        print(f"Error running imessage-exporter: {e}")
        sys.exit(1)
        
    print("\nStep 2: Organizing attachments by contact names...")
    contacts_map = load_macos_contacts()
    
    # We move files from temp to output to be instant and save disk space
    mode = "copy" if keep_temp else "move"
    organize_export_directory(temp_export_dir, output_dir, mode=mode, contacts_map=contacts_map)
    
    if not keep_temp:
        print(f"\nCleaning up temporary export files...")
        shutil.rmtree(temp_export_dir, ignore_errors=True)
        
    print(f"\nAll attachments successfully backed up and organized in:\n  {output_dir}")


def main():
    parser = argparse.ArgumentParser(
        description="Backup and organize iMessage attachments into folders by Contact Name."
    )
    parser.add_argument(
        "-s", "--source",
        help="Path to an existing imessage-exporter export folder (e.g. ~/imessage_export). If omitted, runs a fresh imessage-exporter export."
    )
    default_output_dir = f"~/{datetime.now().strftime('%Y-%m-%d')}_iMessage_Attachments"
    parser.add_argument(
        "-o", "--output",
        default=default_output_dir,
        help=f"Destination directory for organized attachments (default: {default_output_dir})"
    )
    parser.add_argument(
        "-m", "--mode",
        choices=["copy", "move"],
        default="copy",
        help="Whether to 'copy' or 'move' attachments when organizing an existing export directory (default: copy)"
    )
    parser.add_argument(
        "-c", "--copy-method",
        choices=["clone", "basic", "full"],
        default="clone",
        help="Attachment copy method for imessage-exporter (default: clone)"
    )
    parser.add_argument(
        "-f", "--format",
        choices=["txt", "html"],
        default="txt",
        help="Export format for imessage-exporter (default: txt)"
    )
    parser.add_argument(
        "--keep-temp",
        action="store_true",
        help="Keep intermediate transcript files when running a fresh export."
    )
    
    args = parser.parse_args()
    
    if args.source:
        organize_export_directory(args.source, args.output, mode=args.mode)
    else:
        run_full_backup(
            output_dir=args.output,
            copy_method=args.copy_method,
            format_type=args.format,
            keep_temp=args.keep_temp
        )


if __name__ == "__main__":
    main()
