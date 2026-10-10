"""Content-addressed, source-verified figure crops; no OCR or model calls."""
from __future__ import annotations

import hashlib
import io
from pathlib import Path


def put_asset(root, data):
    from PIL import Image
    with Image.open(io.BytesIO(data)) as image:
        if image.format != "PNG" or min(image.size) < 1:
            raise ValueError("PNG asset required")
        image.verify()
    root = Path(root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    sha = hashlib.sha256(data).hexdigest()
    path = root / (sha + ".png")
    if path.resolve().parent != root:
        raise ValueError("asset path escapes root")
    try:
        with path.open("xb") as handle:
            handle.write(data)
    except FileExistsError:
        if path.read_bytes() != data:
            raise ValueError("existing asset has changed; preserve and investigate")
    return {"name": path.name, "sha256": sha}


def render_region(pdf_path, expected_sha256, page, bbox, asset_root, scale=1.5):
    import pypdfium2 as pdfium
    data = Path(pdf_path).read_bytes()
    if hashlib.sha256(data).hexdigest() != expected_sha256:
        raise ValueError("snapshot bytes mismatch")
    if type(page) is not int or page < 1:
        raise ValueError("physical page must be one-based")
    if len(bbox) != 4 or not (0 <= bbox[0] < bbox[2] <= 1 and 0 <= bbox[1] < bbox[3] <= 1):
        raise ValueError("normalized top-left bbox required")
    with pdfium.PdfDocument(data) as doc:
        if page > len(doc):
            raise ValueError("physical page outside snapshot")
        pdf_page = doc[page - 1]
        try:
            bitmap = pdf_page.render(scale=scale)
            try:
                image = bitmap.to_pil()
                width, height = image.size
                box = (int(bbox[0]*width), int(bbox[1]*height),
                       int(bbox[2]*width), int(bbox[3]*height))
                crop = image.crop(box)
                buffer = io.BytesIO()
                crop.save(buffer, format="PNG")
                return put_asset(asset_root, buffer.getvalue())
            finally:
                bitmap.close()
        finally:
            pdf_page.close()


def publish_assets(blocks, source_root, destination_root):
    source_root = Path(source_root).resolve()
    for block in blocks:
        for asset in block.get("chart_assets", []):
            name = asset["sha256"] + ".png"
            if name != asset["name"]:
                raise ValueError("invalid asset identity")
            path = source_root / name
            if path.resolve().parent != source_root:
                raise ValueError("asset source escapes root")
            data = path.read_bytes()
            if hashlib.sha256(data).hexdigest() != asset["sha256"]:
                raise ValueError("asset source changed")
            put_asset(destination_root, data)


def map_native_regions(pdf_path, expected_sha256, page, text, regions):
    """Map reviewed boxes only when the complete non-whitespace layer agrees.

    No fuzzy matching: a different text layer, OCR, ligature difference or
    missing character requires explicit review instead of guessed offsets.
    Returns source-bound spans without rendering or modifying anything.
    """
    import copy
    import pypdfium2 as pdfium
    from .content import digest
    data = Path(pdf_path).read_bytes()
    if hashlib.sha256(data).hexdigest() != expected_sha256:
        raise ValueError("snapshot bytes mismatch")
    mapped = copy.deepcopy(regions)
    document = pdfium.PdfDocument(data)
    pdf_page = document[page - 1]
    textpage = pdf_page.get_textpage()
    try:
        width, height = pdf_page.get_size()
        chars = []
        for i in range(textpage.count_chars()):
            char = textpage.get_text_range(i, 1)
            if not char or char.isspace():
                continue
            if len(char) != 1:
                raise ValueError("ambiguous PDF character mapping")
            left, bottom, right, top = textpage.get_charbox(i)
            chars.append((char, (left+right)/2/width, 1-(bottom+top)/2/height))
        offsets = [(i,c) for i,c in enumerate(text) if not c.isspace()]
        if "".join(c for _,c in offsets) != "".join(c for c,_,_ in chars):
            raise ValueError("text layer does not match indexed text; reviewed exact spans required")
        ownership = [None] * len(text)
        for (offset, _), (_, x, y) in zip(offsets, chars):
            owners = []
            for index, region in enumerate(mapped):
                box = region.get("text_bbox", region["bbox"])
                if box[0] <= x < box[2] and box[1] <= y < box[3]:
                    owners.append(index)
            if len(owners) > 1:
                raise ValueError("overlapping text regions")
            if owners:
                ownership[offset] = owners[0]
        # Spaces between characters owned by the same region inherit it.
        for (left,_),(right,_) in zip(offsets, offsets[1:]):
            if ownership[left] is not None and ownership[left] == ownership[right]:
                ownership[left+1:right] = [ownership[left]]*(right-left-1)
        for region in mapped:
            region["spans"] = []
        remaining = {"id":"unmapped-preserved","kind":"unknown","bbox":[0,0,1,1],"spans":[]}
        start=0
        while start < len(text):
            owner=ownership[start]; end=start+1
            while end < len(text) and ownership[end] == owner:
                end+=1
            region = remaining if owner is None else mapped[owner]
            exclude = owner is not None and region["kind"] == "chart"
            region["spans"].append({"start":start,"end":end,"sha256":digest(text[start:end]),
                                    "action":"exclude" if exclude else "keep",
                                    "role":"unassigned_value" if exclude else "source_text"})
            start=end
        if remaining["spans"]:
            mapped.append(remaining)
        return mapped
    finally:
        textpage.close()
        pdf_page.close()
        document.close()
