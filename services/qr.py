"""QR codes for links shown once on a page: phone pairing (routes/phones.py) and friend share codes (routes/friends.py)."""
import base64
import io

import qrcode


def data_url(text):
    """`text` as a QR code, a PNG data: URL for an <img>."""
    buf = io.BytesIO()
    qrcode.make(text, box_size=8, border=2).save(buf, format='PNG')
    return 'data:image/png;base64,' + base64.b64encode(buf.getvalue()).decode()
