
class BrevService:
    @staticmethod
    def flet_og_send_brev():

        try:
            with open(
                fil_sti, "rb"
            ) as f:
                response = httpx.post(
                    "http://rpa-ats.odknet.dk:8331/render",
                    files={
                        "file": (fil_sti, f)
                    },
                    data={"fields": json.dumps(brev_felter)}     
            )
        except Exception as e:
            logger.error(e)
            raise RuntimeError("Teknisk fejl: Kunne ikke danne brev")

    pdf_path = Path("Danskkursusbrev.pdf")
    pdf_path.write_bytes(response.content)