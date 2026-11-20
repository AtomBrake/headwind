"""What a page hands its script: the <script type="application/json" id=...> block it reads (static/js), parsed."""
import json
import re


def page_data(html, block_id):
    m = re.search(r'<script type="application/json" id="%s">(.*?)</script>' % re.escape(block_id), html, re.S)
    assert m, f'no #{block_id} on the page'
    return json.loads(m.group(1))
