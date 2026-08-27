from asyncio.log import logger
import json
from urllib import response
from pathlib import Path
import httpx
import sbsip
from automation_server_client import WorkItemError



class BrevService:
    # ---------------------------//----------------------------- #
    # Udfyld selv tomme felter, inden du bruger SBSYS Brevsender #
    # ---------------------------//----------------------------- #

    OVERSKRIFT = "Testbrev"
    BESKRIVELSE = "Annes testbrev med SBSYS brevsender i RPA teamet i Odense Kommune"
    # kun påkrævet, hvis der skal oprettes sag:
    SBSYS_SKABELON_ID = ""

    # ---------------------------//----------------------------- #

    @staticmethod
    def _flet_brev(fil_sti: str, brev_felter: dict):
        try:
            with open(fil_sti, "rb") as f:
                response = httpx.post(
                    "http://rpa-ats.odknet.dk:8331/render",
                    files={"file": (fil_sti, f)},
                    data={"fields": json.dumps(brev_felter)},
                )

            response.raise_for_status()

            return response.content

        except Exception as e:
            logger.error(e)
            raise RuntimeError("Teknisk fejl: Kunne ikke danne brev")

    @staticmethod
    def send_brev(pdf_content, fil_sti, cpr, post_nr, adresse):
        pdf_path = Path(fil_sti).with_suffix(".pdf")
        pdf_path.write_bytes(pdf_content)

        if post_nr == "9999" or post_nr is None or post_nr == 9999:
            raise WorkItemError(
                "Borger har ukendt adresse, og kan derfor ikke modtage brevet"
            )
        try:
            sbsip.send_digital_post(
                cpr=cpr,
                overskrift=BrevService.OVERSKRIFT,
                beskrivelse=BrevService.BESKRIVELSE,
                vedhæftet_fil=pdf_path,
                post_nr=post_nr,
                adresse=adresse,
                sbsys_skabelon_id=BrevService.SBSYS_SKABELON_ID,
            )
        except Exception as e:
            pdf_path.unlink()
            logger.error(e)
            raise RuntimeError("Teknisk fejl: Kunne ikke sende brev")

        pdf_path.unlink()

    @staticmethod
    def flet_og_send_brev(fil_sti, brev_felter, cpr, post_nr, adresse):
        pdf_content = BrevService._flet_brev(fil_sti, brev_felter)

        BrevService.send_brev(pdf_content, fil_sti, cpr, post_nr, adresse)
