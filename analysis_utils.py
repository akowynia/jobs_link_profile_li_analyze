import re


def extract_json_from_text(text):
    """Wyciaga obiekt JSON z odpowiedzi modelu, jesli JSON jest opakowany dodatkowym tekstem."""
    if not text:
        return text

    json_block_pattern = r"```json\s*({.*?})\s*```"
    match = re.search(json_block_pattern, text, re.DOTALL)
    if match:
        return match.group(1)

    json_pattern = r"{.*}"
    match = re.search(json_pattern, text, re.DOTALL)
    if match:
        return match.group(0)

    return text
