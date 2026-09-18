import asyncio
import logging
import os
import sys
import sbsip
import argparse

from datafordeler import Datafordeler
from sbsys_brevsender.process.word_service import get_placeholders
from sbsys_brevsender.process.config import get_excel_mapping, load_excel_mapping
from sbsys_brevsender.process.brev_service import BrevService
from odk_tools.reporting import report

from automation_server_client import (
    AutomationServer,
    Workqueue,
    WorkItemError,
    Credential,
    WorkItemStatus,
)

# dine dokumenter med word og excel, indsættes i din .env fil
# ---------------------------//----------------------------- #

# Udfyld selv tomme felter, inden du bruger SBSYS Brevsender #
# ---------------------------//----------------------------- #
# overskrift på brevet
OVERSKRIFT = ""
# beskrivelse af brevet
BESKRIVELSE = ""
# skabelon id er kun påkrævet, hvis der skal oprettes sag:
SBSYS_SKABELON_ID = ""
# ---------------------------//----------------------------- #

# Hvis du skal oprette sag på brev, skal sag_på_brev være true #
# ----------------------------//------------------------------ #
sag_på_brev = False
# ----------------------------//------------------------------ #


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
    obligatoriske_data = {
        placeholder.strip() for placeholder in get_placeholders(args.word_template)
    }

    # henter navn for hver kolonne (eks cpr, adresse, navn osv)
    excel_kolonner = {kolonne.strip().upper() for kolonne in borgere[0].keys()}

    if "CPR" not in excel_kolonner:
        raise ValueError("Manglende CPR kolonne i excel")

    # sammenlign placeholders og excel kolloner
    manglende_kolonner = []

    for felt in obligatoriske_data:
        if felt.upper() not in excel_kolonner:
            manglende_kolonner.append(felt)

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
            felt: normaliseret_borger.get(felt.upper(), "")
            for felt in obligatoriske_data
        }
        # vi skal altid bruge cpr, derfor gemmes cpr også seperat, da brevet kan være foruden placeholders
        cpr = borger["CPR"].replace("-", "")

        data = {
            "borger_data": borger_data,
            "borger_cpr": cpr
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
                    raise WorkItemError(f"Borger er registreret død")

                borger_adresse, borger_post_nr = fordeler.hent_adresse_til_sbsip(cpr)

                try:
                    # send brev - husk at tjek, om du skal lave sag eller ej
                    BrevService.flet_og_send_brev(
                        fil_sti=args.word_template,
                        brev_felter=data["borger_data"],
                        cpr=cpr,
                        post_nr=borger_post_nr,
                        adresse=borger_adresse,
                        overskrift=OVERSKRIFT,
                        beskrivelse=BESKRIVELSE,
                        sbsys_skabelon_id=SBSYS_SKABELON_ID if sag_på_brev else ""
                    )
                except:
                    raise WorkItemError(f"Brev kunne ikke sendes")


                report("sbsys-brevsender", "Brev sendt", {"CPR": cpr})

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


        # Load excel mapping data (skip validation for Windows paths on Linux)
        if os.path.isfile(args.excel_file):
            load_excel_mapping(args.excel_file)
        elif not is_windows_path(args.excel_file):
            parser.error(f"Excel file not found: {args.excel_file}")

        workqueue.clear_workqueue(WorkItemStatus.NEW)
        asyncio.run(populate_queue(workqueue))
        exit(0)


    # ------------------------------------//--------------------------------------
    # fail safes mod ikke at have udfyldt tomme felter
    if not all([OVERSKRIFT.strip(), BESKRIVELSE.strip()]):
        parser.error("Mangler at udfyld overskrift beskrivelse")
    if sag_på_brev == True and not SBSYS_SKABELON_ID:
        parser.error("mangler obligatorisk SBSYS skabelons id")
    # ------------------------------------//--------------------------------------

    # Process workqueue
    asyncio.run(process_workqueue(workqueue))
