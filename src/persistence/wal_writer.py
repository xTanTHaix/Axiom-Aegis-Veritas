"""
AXIOM-AEGIS-VERITAS — Persistence Layer: Write-Ahead Log (WAL) with durability.
Provides crash-safe, ordered entry logging with checksums and recovery support.
"""

import json
import os
import hashlib
import logging
from datetime import datetime
from pathlib import Path
from enum import Enum
from typing import List, Dict, Any, Optional
from dataclasses import dataclass, asdict

logger = logging.getLogger(__name__)

# ─── Constants ────────────────────────────────────────────────────────────
WAL_HEADER_SIZE = 64
ENTRY_PADDING_SIZE = 512
MAGIC_NUMBER = b"AXIOM-WAL"

# ─── Entry Types ──────────────────────────────────────────────────────────
class WALEntryType(Enum):
    """Types of WAL entries."""
    APPEND = "append"
    COMMIT = "commit"
    ROLLBACK = "rollback"


# ─── WAL Header ───────────────────────────────────────────────────────────
@dataclass
class WALHeader:
    """WAL file header."""
    version: int = 1
    entry_count: int = 0
    created_at: float = 0.0
    padding_len: int = 0

    @classmethod
    def from_bytes(cls, data: bytes) -> "WALHeader":
        """Parse header from bytes.

        Header format (64 bytes):
        - magic: 9 bytes (offset 0-8)
        - version: 4 bytes (offset 9-12)
        - entry_count: 16 bytes (offset 13-28)
        - created_at: 8 bytes (offset 29-36)
        - padding_len: 4 bytes (offset 37-40)
        - zero padding up to 64 bytes
        """
        import struct
        if len(data) < WAL_HEADER_SIZE:
            raise ValueError("Header too short")
        if data[:len(MAGIC_NUMBER)] != MAGIC_NUMBER:
            raise ValueError("Invalid WAL magic number")
        offset = len(MAGIC_NUMBER)
        version = struct.unpack("I", data[offset:offset + 4])[0]
        offset += 4
        entry_count = int.from_bytes(data[offset:offset + 16], "big")
        offset += 16
        created_at = struct.unpack("d", data[offset:offset + 8])[0]
        offset += 8
        padding_len = struct.unpack("I", data[offset:offset + 4])[0]
        return cls(
            version=version,
            entry_count=entry_count,
            created_at=created_at,
            padding_len=padding_len,
        )

    def to_bytes(self) -> bytes:
        """Serialize header to bytes.

        Header format (64 bytes):
        - magic: 9 bytes (offset 0-8)
        - version: 4 bytes (offset 9-12)
        - entry_count: 16 bytes (offset 13-28)
        - created_at: 8 bytes (offset 29-36)
        - padding_len: 4 bytes (offset 37-40)
        - zero padding up to 64 bytes
        """
        import struct
        payload = (
            MAGIC_NUMBER
            + struct.pack("I", self.version)
            + self.entry_count.to_bytes(16, "big")
            + struct.pack("d", self.created_at)
            + struct.pack("I", self.padding_len)
        )
        # Pad to exactly WAL_HEADER_SIZE bytes
        return payload.ljust(WAL_HEADER_SIZE, b"\x00")


# ─── WAL Entry ────────────────────────────────────────────────────────────
@dataclass
class WALEntry:
    """A single WAL entry."""
    entry_id: str
    entry_type: WALEntryType
    data: Dict[str, Any]
    timestamp: float
    checksum: str = ""

    def compute_checksum(self) -> str:
        """Compute SHA-256 checksum of entry."""
        import json
        def default(o):
            if isinstance(o, WALEntryType):
                return o.value
            if isinstance(o, datetime):
                return o.isoformat()
            return json.JSONEncoder.default(o)
        data_str = json.dumps(self.to_dict(), sort_keys=True, default=default)
        return hashlib.sha256(data_str.encode("utf-8")).hexdigest()

    def to_bytes(self) -> bytes:
        """Serialize entry to bytes."""
        import json
        entry_dict = asdict(self)
        def default(o):
            if isinstance(o, WALEntryType):
                return o.value
            if isinstance(o, datetime):
                return o.isoformat()
            return json.JSONEncoder.default(o)
        entry_bytes = json.dumps(entry_dict, default=default).encode("utf-8")
        padded = entry_bytes.ljust(ENTRY_PADDING_SIZE, b"\x00")
        return padded

    def to_dict(self) -> Dict[str, Any]:
        """Convert entry to dictionary."""
        return asdict(self)

    @classmethod
    def from_bytes(cls, data: bytes) -> "WALEntry":
        """Parse entry from bytes."""
        if len(data) < ENTRY_PADDING_SIZE:
            raise ValueError("Entry too short")
        
        entry_json = data.rstrip(b"\x00").decode("utf-8")
        entry_dict = json.loads(entry_json)
        return cls(
            entry_id=entry_dict["entry_id"],
            entry_type=WALEntryType(entry_dict["entry_type"]),
            data=entry_dict["data"],
            timestamp=entry_dict["timestamp"],
            checksum=entry_dict["checksum"],
        )


# ─── WAL Writer ───────────────────────────────────────────────────────────
class WALWriter:
    """Writes WAL entries to a file."""

    def __init__(self, path: Path):
        """Initialize writer.

        Args:
            path: Path to WAL file.
        """
        self.path = Path(path)
        self._is_open = False
        self._entry_count = 0
        self._file_handle: Optional[open] = None
        self._reader: Optional[WALReader] = None

    def open(self) -> None:
        """Open the WAL file for writing."""
        if self._is_open:
            logger.warning("WAL already open")
            return

        self._is_open = True

        # Ensure a valid header exists (creates the file or repairs the
        # header WITHOUT destroying any existing entries)
        self._ensure_header()

        # Open file handle for appending entries. Append mode always writes
        # at EOF, i.e. after the header.
        self._file_handle = open(self.path, "ab")

        # Initialize reader for recovery operations
        self._reader = WALReader(self.path)

        logger.info(f"WAL opened at {self.path}")

    def close(self) -> None:
        """Close the WAL file."""
        if not self._is_open:
            return

        if self._file_handle:
            self._file_handle.close()
            self._file_handle = None
            self._is_open = False

        logger.info(f"WAL closed at {self.path}")

    def flush(self) -> None:
        """Flush all data to disk."""
        if not self._is_open:
            return

        if self._file_handle:
            self._file_handle.flush()
            os.fsync(self._file_handle.fileno())

    def _ensure_header(self) -> None:
        """Ensure WAL header exists, preserving any existing entry data."""
        # If file doesn't exist (or is empty), create it with a fresh header
        if not self.path.exists() or self.path.stat().st_size == 0:
            header = WALHeader(created_at=datetime.now().timestamp())
            with open(self.path, "wb") as header_file:
                header_file.write(header.to_bytes())
            logger.info(f"WAL header created at {self.path}")
            return

        # Read existing content to check header validity
        with open(self.path, "rb") as f:
            f.seek(0)
            header_data = f.read(WAL_HEADER_SIZE)

        if len(header_data) == WAL_HEADER_SIZE and header_data[:len(MAGIC_NUMBER)] == MAGIC_NUMBER:
            # Header already exists and is valid — keep the file untouched
            return

        # Header is missing or corrupted — rebuild it WITHOUT truncating
        # entries. Entries live after the header region; preserve them all.
        with open(self.path, "rb") as f:
            existing_data = f.read()
        entry_data = existing_data[WAL_HEADER_SIZE:]

        header = WALHeader(created_at=datetime.now().timestamp())
        with open(self.path, "wb") as header_file:
            header_file.write(header.to_bytes())
            header_file.write(entry_data)
        logger.info(
            f"WAL header recreated at {self.path} "
            f"(preserved {len(entry_data)} bytes of entry data)"
        )

    def append(self, entry_data: Dict[str, Any], entry_type: WALEntryType = WALEntryType.APPEND) -> WALEntry:
        """Append a new entry to the WAL.

        Args:
            entry_data: Entry data as dictionary.
            entry_type: Type of entry (default: APPEND).

        Returns:
            Created WALEntry object.
        """
        if not self._is_open:
            raise RuntimeError("WAL not open. Call open() first.")

        # Generate entry ID
        entry_id = f"entry_{self._entry_count:08d}"

        # Create entry
        wal_entry = WALEntry(
            entry_id=entry_id,
            entry_type=entry_type,
            data=entry_data,
            timestamp=datetime.now().timestamp(),
            checksum="",  # Will be computed after writing
        )

        # Compute checksum FIRST (before writing)
        wal_entry.checksum = wal_entry.compute_checksum()

        # Write entry to file with checksum already computed
        entry_bytes = wal_entry.to_bytes()
        self._file_handle.write(entry_bytes)
        logger.info(f"WAL wrote {len(entry_bytes)} bytes to file")

        # Update entry count
        self._entry_count += 1

        # Flush to disk
        self.flush()

        # Persist the updated entry count into the header
        self._sync_header_count()

        logger.info(f"WAL appended entry {entry_id}")
        return wal_entry

    def _sync_header_count(self) -> None:
        """Persist the current entry count into the WAL header."""
        try:
            with open(self.path, "r+b") as f:
                raw = f.read(WAL_HEADER_SIZE)
                if len(raw) == WAL_HEADER_SIZE:
                    try:
                        header = WALHeader.from_bytes(raw)
                    except ValueError:
                        header = WALHeader(created_at=datetime.now().timestamp())
                    header.entry_count = self._entry_count
                    f.seek(0)
                    f.write(header.to_bytes())
        except OSError as e:
            logger.warning(f"Failed to update WAL header entry count: {e}")

    def read_all_entries(self) -> List[WALEntry]:
        """Read all entries from the WAL file.

        Returns:
            List of all WAL entries.
        """
        # Use the reader class to read entries
        if self._reader:
            return self._reader.read_all_entries()
        return []


# ─── WAL Reader ───────────────────────────────────────────────────────────
class WALReader:
    """Reads WAL entries from a file."""

    def __init__(self, path: Path):
        """Initialize reader.

        Args:
            path: Path to WAL file.
        """
        self.path = path
        self.entries: List[WALEntry] = []

    def read_all_entries(self) -> List[WALEntry]:
        """Read all entries from the WAL file.

        Returns:
            List of all WAL entries.
        """
        if not self.path.exists():
            return []

        entries: List[WALEntry] = []
        with open(self.path, "rb") as f:
            # Read all data
            data = f.read()

            # Check minimum size (header + at least one entry)
            if len(data) < WAL_HEADER_SIZE:
                logger.warning("WAL file too short")
                return entries

            # Parse header
            header = WALHeader.from_bytes(data[:WAL_HEADER_SIZE])

            # Skip header
            entry_data = data[WAL_HEADER_SIZE:]

            # Parse entries - each entry is padded to ENTRY_PADDING_SIZE
            offset = 0
            num_entries_read = 0
            while offset < len(entry_data):
                # Get remaining data from current offset
                remaining_data = entry_data[offset:]
                if not remaining_data:
                    break

                # Read the entry chunk with full padding
                chunk = entry_data[offset:offset + ENTRY_PADDING_SIZE]
                if not chunk or len(chunk) < ENTRY_PADDING_SIZE:
                    break

                # Parse entry
                try:
                    entry = WALEntry.from_bytes(chunk)
                    entries.append(entry)
                    num_entries_read += 1
                except (json.JSONDecodeError, KeyError, ValueError) as e:
                    logger.warning(f"WAL entry corrupted at offset {offset}: {e}")
                    break
                offset += ENTRY_PADDING_SIZE

            # Verify we read the expected number of entries
            if num_entries_read != header.entry_count:
                logger.warning(
                    f"Read {num_entries_read} entries but header reports {header.entry_count} entries"
                )

        logger.info(f"WAL read {len(entries)} entries from {self.path}, file_size={len(data)}, header_entry_count={header.entry_count}")
        if len(entries) == 0 and len(data) > WAL_HEADER_SIZE:
            logger.warning(f"No entries found but file has data. Header entry_count={header.entry_count}")
        return entries