import asyncio
import logging
import os
import sys
import sbsip
from datafordeler import Datafordeler
import argparse

from process.word_template import get_placeholders
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


    #TODO: vigtigt at brev der ikke har brug for placeholders stadig kan sendes


async def populate_queue(workqueue: Workqueue):
    logger = logging.getLogger(__name__)

    logger.info("Hello from populate workqueue!")
    mapping = get_excel_mapping()


    # henter navn på på excel ark
    sheet_name = next(iter(mapping.keys()))
    borgere = mapping[sheet_name]

    # henter obligatoriske felter / tuborgklammer i word brev
    obligatoriske_data = get_placeholders(args.word_template)

    # henter navn for hver kolonne (eks cpr, adresse, navn osv)
    excel_kolonner = {
        kolonne.strip().upper()
        for kolonne in borgere[0].keys()
    }

    if "CPR" not in excel_kolonner:
        raise ValueError (
            "Manglende CPR kolonne i excel"
        )


    # sammenlign placeholders og excel kolloner
    # hvis der er flere excel kolonner end placeholders i brevet, bliver de ignoreret, da de ikke er en del af obligatoriske_data
    manglende_kolonner = obligatoriske_data - excel_kolonner


    if manglende_kolonner:
        raise ValueError(
           "Uoverenstemmelse mellem obligatoriske felter i brevet og tilgængelige kolonner i excel"
            f"Manglende kollone i excel: {', '.join(sorted(manglende_kolonner))}"
        )

    # normalisere og trækker data ud for hvert enkelte borger i excel
    for borger in borgere:
        normaliseret_borger = {
            kolonne.strip().upper(): værdi
            for kolonne, værdi in borger.items()
        }

        borger_data = {
            felt: normaliseret_borger.get(felt, "")
            for felt in obligatoriske_data
        }
        cpr = borger["CPR"]

        data = {"borger_data": borger_data, "borger": cpr}
    
        # tjek om item allerede er i kø inden det bliver sendt ned til process
        if not workqueue.get_item_by_reference(cpr, status=WorkItemStatus.IN_PROGRESS):
            workqueue.add_item(data=data, reference=str(borger["CPR"]))


    print("hej")


async def process_workqueue(workqueue: Workqueue):
    logger = logging.getLogger(__name__)

    logger.info("Hello from process workqueue!")

    for item in workqueue:
        with item:
            data = item.data  # Item data deserialized from json as dict
            cpr = data["borger_data"]["CPR"]

            try:

                # hvis borger har manglende data, skal item fejle i proces, så det kommer i rapporten, og de manuelt selv må sende brevet i stedet
                manglende_værdier = {
                    felt
                    for felt, værdi in data["borger_data"].items()
                    if værdi is None or not str(værdi).strip()
                }
                if manglende_værdier:
                    raise ValueError(
                        f"Borger med CPR {cpr} mangler obligatoriske værdier"
                    )


                #TODO: brug datafordeler til at se om borger er død



                #TODO: post nr ok?

                

                #TODO: Brug data og indsæt i word brev ( test_datafordeler.docx ). Måske noget sikring om det er rigtige data inden


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
        default=os.environ.get("WORD_TEMPLATE_PATH"),
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
