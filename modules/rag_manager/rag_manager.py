"""
RAG Manager Module

Core functionality for document storage and management.
"""

import os
import json
from pathlib import Path
import shutil
from datetime import datetime
from typing import List, Dict, Optional, Tuple
from shared.logging import log
from shared.config import get_config

class RAGManager:
    """Manages RAG documents storage and operations."""

    def __init__(self):
        self.config = get_config()
        rag_config = self.config.get("rag_manager", {})
        self.data_dir = Path(rag_config.get("data_directory", "./data/rag_documents"))
        self.allowed_extensions = rag_config.get("allowed_extensions", [".txt", ".pdf", ".md"])
        self.max_file_size_mb = rag_config.get("max_file_size_mb", 10)

        # Store config for easy access if needed
        self.rag_config = rag_config

        # Initialize data directory
        self._init_data_directory()

        # Load documents metadata
        self.metadata_file = self.data_dir / "metadata.json"
        self.documents = self._load_metadata()

    def _init_data_directory(self):
        """Initialize the data directory structure."""
        try:
            self.data_dir.mkdir(parents=True, exist_ok=True)
            log("info", f"RAG data directory initialized: {self.data_dir}")
        except Exception as e:
            log("error", f"Failed to initialize RAG data directory: {str(e)}")
            raise

    def _load_metadata(self) -> Dict:
        """Load documents metadata from JSON file."""
        if self.metadata_file.exists():
            try:
                with open(self.metadata_file, 'r') as f:
                    return json.load(f)
            except Exception as e:
                log("error", f"Failed to load metadata: {str(e)}")
                return {}
        return {}

    def _save_metadata(self):
        """Save documents metadata to JSON file."""
        try:
            with open(self.metadata_file, 'w') as f:
                json.dump(self.documents, f, indent=2)
            log("debug", f"Metadata saved: {len(self.documents)} documents")
        except Exception as e:
            log("error", f"Failed to save metadata: {str(e)}")

    def is_valid_file(self, file_path: str) -> Tuple[bool, str]:
        """Validate if a file can be uploaded."""
        file_size_mb = os.path.getsize(file_path) / (1024 * 1024)

        if file_size_mb > self.max_file_size_mb:
            return False, f"File too large ({file_size_mb:.2f}MB > {self.max_file_size_mb}MB)"

        file_ext = os.path.splitext(file_path)[1].lower()
        if file_ext not in self.allowed_extensions:
            return False, f"Unsupported file extension: {file_ext}"

        return True, ""

    def upload_document(self, source_path: str, original_filename: str) -> Optional[str]:
        """Upload a document to the RAG storage."""
        try:
            # Validate file
            is_valid, error_msg = self.is_valid_file(source_path)
            if not is_valid:
                log("warning", f"File validation failed: {error_msg}")
                return None

            # Generate unique filename
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            file_ext = os.path.splitext(original_filename)[1]
            unique_filename = f"{timestamp}_{original_filename}"
            dest_path = self.data_dir / unique_filename

            # Copy file
            shutil.copy2(source_path, dest_path)

            # Add to metadata
            file_size = os.path.getsize(dest_path)
            file_size_mb = file_size / (1024 * 1024)

            self.documents[unique_filename] = {
                "original_filename": original_filename,
                "uploaded_at": datetime.now().isoformat(),
                "file_size": file_size,
                "file_size_mb": round(file_size_mb, 2),
                "file_extension": file_ext,
                "file_path": str(dest_path)
            }

            # Save metadata
            self._save_metadata()

            log("info", f"Document uploaded: {original_filename} -> {unique_filename}")
            return unique_filename

        except Exception as e:
            log("error", f"Failed to upload document {original_filename}: {str(e)}", exc_info=True)
            return None

    def delete_document(self, filename: str) -> bool:
        """Delete a document from RAG storage."""
        try:
            if filename not in self.documents:
                log("warning", f"Document not found in metadata: {filename}")
                return False

            # Get file path
            file_path = Path(self.documents[filename]["file_path"])

            # Delete file
            if file_path.exists():
                file_path.unlink()
                log("debug", f"File deleted: {file_path}")

            # Remove from metadata
            del self.documents[filename]
            self._save_metadata()

            log("info", f"Document deleted: {filename}")
            return True

        except Exception as e:
            log("error", f"Failed to delete document {filename}: {str(e)}", exc_info=True)
            return False

    def get_document_list(self) -> List[Dict]:
        """Get list of all documents with metadata."""
        result = []
        for filename, metadata in self.documents.items():
            result.append({
                "filename": filename,
                "original_filename": metadata["original_filename"],
                "uploaded_at": metadata["uploaded_at"],
                "file_size_mb": metadata["file_size_mb"],
                "file_extension": metadata["file_extension"]
            })

        # Sort by upload date (newest first)
        result.sort(key=lambda x: x["uploaded_at"], reverse=True)
        return result

    def get_document_count(self) -> int:
        """Get total number of documents."""
        return len(self.documents)

    def get_total_size_mb(self) -> float:
        """Get total size of all documents in MB."""
        total = sum(doc["file_size_mb"] for doc in self.documents.values())
        return round(total, 2)

    def get_document_info(self, filename: str) -> Optional[Dict]:
        """Get detailed information about a document."""
        return self.documents.get(filename)

    def clear_all_documents(self) -> bool:
        """Clear all documents (admin function)."""
        try:
            # Delete all files
            for filename, metadata in self.documents.items():
                file_path = Path(metadata["file_path"])
                if file_path.exists():
                    file_path.unlink()

            # Clear metadata
            self.documents = {}
            self._save_metadata()

            log("info", "All documents cleared")
            return True

        except Exception as e:
            log("error", f"Failed to clear all documents: {str(e)}", exc_info=True)
            return False

# Create a singleton instance
rag_manager = RAGManager()
