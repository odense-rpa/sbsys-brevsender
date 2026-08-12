from typing import Dict, List
from openpyxl import load_workbook

# Denne fil er til at håndtere excel mapping. 
# Den indlæser en excel fil og gemmer mappingen i en global variabel, som kan hentes med get_excel_mapping. 
# Derudover er der en funktion get_regler, som henter værdierne fra "Liste" arket i excel filen.


# Global mappings - each contains workbook name -> list of row dictionaries
excel_mappings: Dict[str, List[Dict[str, str]]] = {}


def get_excel_mapping() -> Dict[str, List[Dict[str, str]]]:
    """Henter excel-mapping"""
    if not excel_mappings:
        raise ValueError("excel-mapping er ikke indlæst, brug load_excel_mapping først")
    return excel_mappings


def load_excel_mapping(file_path: str, mapping_type: str = "excel"):
    """
    Indlæser excel-mapping fra en fil og gemmer den i den tilsvarende globale mapping.
    Hver workbook (worksheet) gemmes som en liste af rækker (dictionaries).

    Args:
        file_path: Stien til Excel-filen
        mapping_type: Type af mapping ("excel" eller "citizen")
    """
    global excel_mappings

    try:
        # Load workbook
        workbook = load_workbook(file_path)

        # Initialize mapping dictionary for all worksheets
        all_sheets_mapping: Dict[str, List[Dict[str, str]]] = {}

        # Process each worksheet
        for sheet_name in workbook.sheetnames:
            worksheet = workbook[sheet_name]

            # Determine header row: find the first non-empty row within the first 5 rows
            max_header_row_search = 5
            header_row = None
            header_row_index = 1
            for r in range(1, min(max_header_row_search, worksheet.max_row) + 1):
                row_cells = worksheet[r]
                if any(cell.value and str(cell.value).strip() for cell in row_cells):
                    header_row = row_cells
                    header_row_index = r
                    break
            if header_row is None:
                # Fallback to first row if nothing found
                header_row = worksheet[1]
                header_row_index = 1

            headers = []
            for cell in header_row:
                if cell.value and str(cell.value).strip():
                    headers.append(str(cell.value).strip())

            if not headers:
                # If the header row contains no explicit headers (e.g., empty or merged cells),
                # create placeholder headers for each column so data rows are still captured.
                headers = [f"col_{i+1}" for i in range(worksheet.max_column)]

            # Initialize list for rows
            rows = []

            # Process each data row (starting after the detected header row)
            for row in worksheet.iter_rows(
                min_row=header_row_index + 1, values_only=True
            ):
                # Create dictionary for this row
                row_dict = {}
                for idx, header in enumerate(headers):
                    if idx < len(row):
                        cell_value = row[idx]
                        if cell_value is not None:
                            row_dict[header] = str(cell_value).strip()
                        else:
                            row_dict[header] = ""
                    else:
                        row_dict[header] = ""

                # Only add row if it has at least one non-empty value
                if any(value for value in row_dict.values()):
                    rows.append(row_dict)

            # Add this sheet's rows to the overall mapping
            all_sheets_mapping[sheet_name] = rows

        # Assign to the appropriate global mapping
        if mapping_type == "excel":
            excel_mappings = all_sheets_mapping
        else:
            raise ValueError(f"Unknown mapping_type: {mapping_type}. Expected 'excel'")

    except Exception as e:
        raise RuntimeError(
            f"Failed to load mapping from Excel file '{file_path}': {str(e)}"
        ) from e


def get_regler() -> List[str]:
    """Return the list of values from the 'Liste' worksheet.

    This function returns the first non-empty cell value from each row in the
    'Liste' sheet (or 'liste' variant). Raises ValueError if no values are found.
    """
    mapping = get_excel_mapping()
    # Case-insensitive lookup for 'Liste' sheet name
    liste_rows = mapping.get("Liste")
    if not liste_rows:
        liste_rows = next(
            (rows for name, rows in mapping.items() if name and name.strip().lower() == "liste"),
            [],
        )
    # Final fallback to lowercase key if present
    if not liste_rows:
        liste_rows = mapping.get("liste", [])