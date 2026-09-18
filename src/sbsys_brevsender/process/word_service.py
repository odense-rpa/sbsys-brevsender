import re

from docx import Document


def get_placeholders(document_path: str) -> list[str]:

    document = Document(document_path)

    paragraphs = list(document.paragraphs)
    for table in document.tables:
        for row in table.rows:
            for cell in row.cells:
                paragraphs.extend(cell.paragraphs)

    text = "\n".join(paragraph.text for paragraph in paragraphs)

    pattern = r"\{\{(.*?)\}\}"

    placeholders = {match.strip() for match in re.findall(pattern, text)}

    return placeholders