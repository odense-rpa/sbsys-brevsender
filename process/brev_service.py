from asyncio.log import logger
import json
from urllib import response
from pathlib import Path
import httpx
import sbsip
from automation_server_client import WorkItemError


class BrevService:


    @staticmethod
    def flet_og_send_brev(fil_sti: str, brev_felter: dict, cpr: str, post_nr, adresse: str, overskrift: str, beskrivelse: str, sbsys_skabelon_id: str = ""):
        """Render the template, write PDF, validate address, send and cleanup.

        This consolidates rendering and sending into one method and preserves
        previous error semantics.
        """
        # Render brev
        try:
            with open(fil_sti, "rb") as f:
                response = httpx.post(
                    "http://rpa-ats.odknet.dk:8331/render",
                    files={"file": (fil_sti, f)},
                    data={"fields": json.dumps(brev_felter)},
                )

            response.raise_for_status()
            pdf_content = response.content
        except Exception as e:
            logger.error(e)
            raise RuntimeError("Teknisk fejl: Kunne ikke danne brev")

        # Write PDF to disk
        pdf_path = Path(fil_sti).with_suffix(".pdf")
        pdf_path.write_bytes(pdf_content)

        # Validate address
        if post_nr == "9999" or post_nr is None or post_nr == 9999:
            # Clean up written file before raising
            try:
                pdf_path.unlink()
            except Exception:
                pass
            raise WorkItemError(
                "Borger har ukendt adresse, og kan derfor ikke modtage brevet"
            )

        # Send via sbsip
        try:
            sbsip.send_digital_post(
                cpr=cpr,
                overskrift=overskrift,
                beskrivelse=beskrivelse,
                vedhæftet_fil=pdf_path,
                post_nr=post_nr,
                adresse=adresse,
                sbsys_skabelon_id=sbsys_skabelon_id,
            )
        except Exception as e:
            try:
                pdf_path.unlink()
            except Exception:
                pass
            logger.error(e)
            raise RuntimeError("Teknisk fejl: Kunne ikke sende brev")

        # Cleanup
        try:
            pdf_path.unlink()
        except Exception:
            logger.warning("Kunne ikke fjerne midlertidig pdf: %s", str(pdf_path))
