import asyncio
import logging
import os
import sys
import sbsip
import argparse

from datafordeler import Datafordeler
from process.word_template import get_placeholders
from process.config import get_excel_mapping, load_excel_mapping
from process.brev_service import BrevService
from odk_tools.tracking import Tracker
from odk_tools.reporting import report
from pathlib import Path

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
    # breve, hvor der ikke er brug for placeholders, går igennem med en borger ved kun at gemme cpr til item

    logger = logging.getLogger(__name__)

    logger.info("Hello from populate workqueue!")
    mapping = get_excel_mapping()

    # henter navn på på excel ark
    sheet_name = next(iter(mapping.keys()))
    borgere = mapping[sheet_name]

    # henter obligatoriske felter / tuborgklammer i word brev
    obligatoriske_data = get_placeholders(args.word_template)

    # henter navn for hver kolonne (eks cpr, adresse, navn osv)
    excel_kolonner = {kolonne.strip().upper() for kolonne in borgere[0].keys()}

    if "CPR" not in excel_kolonner:
        raise ValueError("Manglende CPR kolonne i excel")

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
            kolonne.strip().upper(): værdi for kolonne, værdi in borger.items()
        }

        borger_data = {
            felt: normaliseret_borger.get(felt, "") for felt in obligatoriske_data
        }
        # vi skal altid bruge cpr, derfor gemmes cpr seperat, da brevet kan være foruden placeholders
        cpr = borger["CPR"].replace("-", "")

        data = {
            "borger_data": borger_data,
            "borger_cpr": cpr,
            "obligatoriske_data": list(obligatoriske_data),
        }

        # tjek om item allerede er i kø inden det bliver sendt ned til process
        if not workqueue.get_item_by_reference(cpr, status=WorkItemStatus.IN_PROGRESS):
            workqueue.add_item(data=data, reference=str(cpr))


async def process_workqueue(workqueue: Workqueue):
    logger = logging.getLogger(__name__)

    logger.info("Hello from process workqueue!")

    for item in workqueue:
        with item:
            data = item.data  # Item data deserialized from json as dict
            cpr = data["borger_cpr"]
            #brev_felter = data["obligatoriske_data"]

            try:
                # hvis borger har manglende data, skal item fejle i proces, så det kommer i rapporten, og de manuelt selv må sende brevet i stedet
                manglende_værdier = {
                    felt
                    for felt, værdi in data["borger_data"].items()
                    if værdi is None or not str(værdi).strip()
                }
                if manglende_værdier:
                    raise WorkItemError(
                        f"Borger med CPR: {cpr} mangler obligatoriske værdier"
                    )

                personoplysninger = fordeler.hent_personoplysninger(cpr)
                if personoplysninger["Person"]["status"] == "doed":
                    raise ValueError(f"Borger er registreret død")

                borger_adresse, borger_post_nr = fordeler.hent_adresse_til_sbsip(cpr)

                # TODO: det skal være muligt at kunne oprette sag, når man sender brevet. Men ikke altid. Når man skal oprette sag, kræver det skabelons id

                BrevService.flet_og_send_brev(
                    fil_sti=args.word_template,
                    brev_felter=data["borger_data"],
                    cpr=cpr,
                    post_nr=borger_post_nr,
                    adresse=borger_adresse,
                )

                report("sbsys-brevsender", "Brev sendt", {"CPR": cpr})

                print("hej")

            except WorkItemError as e:
                # A WorkItemError represents a soft error that indicates the item should be passed to manual processing or a business logic fault
                # reportere fejl ved brev sendelse
                report("sbsys-brevsender", "Brev blev ikke sendt", {"CPR": cpr})

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
            parser.error("--excel-file is required for populate_queue")

        # fail safe mod ikke at have udfyldt tomme felter 
        if not all([BrevService.OVERSKRIFT.strip(), BrevService.BESKRIVELSE.strip()]):
            parser.error(
                "Mangler at udfyld overskrift, beskrivelse og sbsys_skabelon_id i brev_service"
            )

        # Load excel mapping data (skip validation for Windows paths on Linux)
        if os.path.isfile(args.excel_file):
            load_excel_mapping(args.excel_file)
        elif not is_windows_path(args.excel_file):
            parser.error(f"Excel file not found: {args.excel_file}")

        workqueue.clear_workqueue(WorkItemStatus.NEW)
        asyncio.run(populate_queue(workqueue))
        exit(0)

    # Process workqueue
    asyncio.run(process_workqueue(workqueue))
