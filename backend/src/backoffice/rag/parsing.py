"""Parse the hotel documents (PDF, Word) into structured DoclingDocuments.

Docling runs locally. It reads the layout of each page (headings, paragraphs, lists, tables,
page headers/footers) instead of just extracting raw text, so the chunker can later split the
document along its real sections.
"""

from pathlib import Path

from docling.document_converter import DocumentConverter
# Imported from the module where the class is defined: the shorter path (docling_core.types.doc)
# works at runtime but doesn't declare it as exported, so the editor's type checker flags it.
from docling_core.types.doc.document import DoclingDocument

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


def parse_documents(paths: list[Path]) -> dict[str, DoclingDocument]:
    """
    Parse every file with ONE converter (creating it loads Docling's layout models, which is slow,
    so it is done once and reused for all files).

    Shape returned: dict, key = file name, value = Docling's structured version of that file
      {
          "overlook_guest_information.pdf": DoclingDocument(...),   # headings, texts, lists, pages
          "overlook_spa_price_list.pdf":    DoclingDocument(...),   # ... plus tables
          ...
      }
    """
    converter = DocumentConverter()
    return {path.name: converter.convert(path).document for path in paths}
