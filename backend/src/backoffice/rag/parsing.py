"""Parse the hotel documents (PDF, Word) into structured DoclingDocuments.

Docling runs locally. It reads the layout of each page (headings, paragraphs, lists, tables,
page headers/footers) instead of just extracting raw text, so the chunker can later split the
document along its real sections.
"""

from functools import lru_cache
from io import BytesIO
from pathlib import Path

from docling.document_converter import DocumentConverter
# Imported from the module where the class is defined: the shorter path (docling_core.types.doc)
# works at runtime but doesn't declare it as exported, so the editor's type checker flags it.
from docling_core.types.doc.document import DoclingDocument
from docling_core.types.io import DocumentStream

# parsing.py is at backend/src/backoffice/rag/ -> four levels up is the repo root.
DOCUMENTS_DIR = Path(__file__).resolve().parents[4] / "data" / "documents"
SUPPORTED_SUFFIXES = {".pdf", ".docx"}


def list_documents(folder: Path = DOCUMENTS_DIR) -> list[Path]:
    """
    The documents to index: every PDF and Word file in the folder, sorted by name.

    Shape returned: list of paths
      [
          Path(".../data/documents/overlook_guest_information.pdf"),
          Path(".../data/documents/overlook_house_rules_and_policies.docx"),
          ...
      ]
    """
    return sorted(p for p in folder.iterdir() if p.suffix.lower() in SUPPORTED_SUFFIXES)


@lru_cache(maxsize=1)
def get_converter() -> DocumentConverter:
    """
    Docling's converter, created ONCE per program and reused (creating it loads the layout models,
    which takes seconds). lru_cache = Python's built-in "remember the result of this function":
    the first call creates the converter, every later call returns the same one.
    """
    return DocumentConverter()


def parse_documents(paths: list[Path]) -> dict[str, DoclingDocument]:
    """
    Parse every file with the shared converter.

    Shape returned: dict, key = file name, value = Docling's structured version of that file
      {
          "overlook_guest_information.pdf": DoclingDocument(...),   # doc.texts: headings, paragraphs, lists
          "overlook_spa_price_list.pdf":    DoclingDocument(...),   # doc.texts + doc.tables (the price table)
          ...
      }
    """
    converter = get_converter()
    return {path.name: converter.convert(path).document for path in paths}


def parse_bytes(filename: str, data: bytes) -> DoclingDocument:
    """
    Parse a file that is in MEMORY rather than on disk, e.g. a PDF attached to an email.

    DocumentStream is Docling's wrapper for "a file name + its bytes": BytesIO(data) makes the bytes
    readable like an open file. The file name matters: Docling uses its extension (.pdf) to choose
    how to read it.

    Example: parse_bytes("FRP-INV-2026-1184.pdf", b"%PDF-1.7 ...") -> DoclingDocument with the invoice's
             texts and its line-items table.
    """
    return get_converter().convert(DocumentStream(name=filename, stream=BytesIO(data))).document
