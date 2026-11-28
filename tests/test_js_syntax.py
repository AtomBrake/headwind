"""Every page script parses: one stray quote (a "week's" in a single-quoted string, 0.7.62) stops a whole file, and every handler on its
page with it. Needs Node; skipped without it."""
import glob
import os
import shutil
import subprocess

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NODE = shutil.which('node')


@pytest.mark.skipif(not NODE, reason='no node to parse the scripts with')
@pytest.mark.parametrize('path', sorted(glob.glob(os.path.join(ROOT, 'static', 'js', '*.js'))), ids=os.path.basename)
def test_a_page_script_parses(path):
    r = subprocess.run([NODE, '--check', path], capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, r.stderr
