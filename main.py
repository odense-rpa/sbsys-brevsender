import asyncio
import logging
import os
import sys
import sbsip
from datafordeler import Datafordeler
import argparse

from process.config import get_excel_mapping, load_excel_mapping, get_regler

from automation_server_client import (
    AutomationServer,
    Workqueue,
    WorkItemError,
    Credential,
    WorkItemStatus,
)

proces_navn = "SBSYS-brevsender"
fordeler: Datafordeler


async def populate_queue(workqueue: Workqueue):
    logger = logging.getLogger(__name__)

    logger.info("Hello from populate workqueue!")

    #TODO: indsæt item i queue for at kunne teste excel
    load_excel_mapping(os.getenv("EXCEL_MAPPING_PATH"))
    mapping = get_excel_mapping()
    logger.info(f"Fundne worksheets: {list(mapping.keys())}")

    sheet_name = next(iter(mapping.keys()))
    borgere = mapping[sheet_name]

    #TODO: right now the for loop is veru specific, but is there a way to make it more generic? Should i list all possible scenarios of column names?
    for borger in borgere:
        cpr = borger.get("CPR", "")
        navn = borger.get("Navn", "")
        adresse = borger.get("Adresse", "") 


    print("hej")


async def process_workqueue(workqueue: Workqueue):
    logger = logging.getLogger(__name__)

    logger.info("Hello from process workqueue!")

    for item in workqueue:
        with item:
            data = item.data  # Item data deserialized from json as dict

            try:
                # Process the item here


                pass
            except WorkItemError as e:
                # A WorkItemError represents a soft error that indicates the item should be passed to manual processing or a business logic fault
                logger.error(f"Error processing item: {data}. Error: {e}")
                item.fail(str(e))


if __name__ == "__main__":
    ats = AutomationServer.from_environment()
    workqueue = ats.workqueue()

    # Initialize external systems for automation here..
    sbsip_credential = Credential.get_credential("SBSip - produktion")

    parser = argparse.ArgumentParser(description=proces_navn)

    parser.add_argument(
        "--queue",
        action="store_true",
        help="Udfyld køen og afslut",
    )

    certifikat_sti = os.getenv("CERTIFICATES", "certificates")
    fordeler = Datafordeler(
        certifikat_sti=os.path.join(certifikat_sti, "datafordeler.crt"),
        certifikat_nøglefil=os.path.join(certifikat_sti, "datafordeler.key"),
    )

    parser.add_argument(
        "--excel-file",
        default=os.environ.get("EXCEL_MAPPING_PATH"),
        help="Path to the Excel file containing mapping data (default: input/Test_Regelsæt.xlsx)",
    )

    parser.add_argument(
        "--word-template",
        default="input/brev_template.docx",
        help="Path to the Word template for letter generation",
    )
    args = parser.parse_args()

    sbsip.start_sbsip(
        brugernavn=sbsip_credential.username,
        adgangskode=sbsip_credential.password,
    )


     # Validate Excel files exists (skip validation for Windows paths on Linux)
    def is_windows_path(path: str) -> bool:
        """Check if path is a Windows path (has drive letter or UNC path)"""
        return (
            (len(path) > 1 and path[1] == ":")
            or path.startswith("\\\\")
            or path.startswith("//")
        )


    # Queue management
    if "--queue" in sys.argv:
        if not args.excel_file:
            parser.error('--excel-file is required for populate_queue')


        # Load excel mapping data (skip validation for Windows paths on Linux)
        if os.path.isfile(args.excel_file):
            load_excel_mapping(args.excel_file)
        elif not is_windows_path(args.excel_file):
            parser.error(f"Excel file not found: {args.excel_file}")

        # Get rules from excel mapping (implemented in process.config)
        regler = get_regler()


        workqueue.clear_workqueue(WorkItemStatus.NEW)
        asyncio.run(populate_queue(workqueue))
        exit(0)

    # Process workqueue
    asyncio.run(process_workqueue(workqueue))
