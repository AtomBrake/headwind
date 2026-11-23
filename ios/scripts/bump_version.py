#!/usr/bin/env python3
"""Bump the iPhone and Watch apps' version in ios/Config/Version.xcconfig before a build goes onto a device.

    python3 ios/scripts/bump_version.py           # 0.1.1 -> 0.1.2: every build that goes onto a phone or Watch
    python3 ios/scripts/bump_version.py minor     # 0.1.7 -> 0.2.0: needs a newer server, or changes data a step back can't read
    python3 ios/scripts/bump_version.py major     # 0.9.3 -> 1.0.0: out of beta
    python3 ios/scripts/bump_version.py --show    # print the current version and build, change nothing

The build number (CFBundleVersion) goes up by one every time, whichever part changes.
"""
import pathlib
import re
import sys

XCCONFIG = pathlib.Path(__file__).resolve().parent.parent / 'Config' / 'Version.xcconfig'
VERSION = re.compile(r'^(MARKETING_VERSION\s*=\s*)(\d+)\.(\d+)\.(\d+)\s*$', re.M)
BUILD = re.compile(r'^(CURRENT_PROJECT_VERSION\s*=\s*)(\d+)\s*$', re.M)


def read(text):
    v, b = VERSION.search(text), BUILD.search(text)
    if not v or not b:
        sys.exit(f'{XCCONFIG} needs MARKETING_VERSION = x.y.z and CURRENT_PROJECT_VERSION = n')
    return [int(v.group(i)) for i in (2, 3, 4)], int(b.group(2))


def bumped(version, part):
    major, minor, patch = version
    if part == 'major':
        return [major + 1, 0, 0]
    if part == 'minor':
        return [major, minor + 1, 0]
    return [major, minor, patch + 1]


def main(args):
    part = args[0] if args else 'patch'
    if part not in ('patch', 'minor', 'major', '--show'):
        sys.exit(__doc__)
    text = XCCONFIG.read_text(encoding='utf-8')
    version, build = read(text)
    if part == '--show':
        print(f"{'.'.join(map(str, version))} ({build})")
        return
    new_version, new_build = '.'.join(map(str, bumped(version, part))), build + 1
    text = VERSION.sub(lambda m: m.group(1) + new_version, text, count=1)
    text = BUILD.sub(lambda m: m.group(1) + str(new_build), text, count=1)
    XCCONFIG.write_text(text, encoding='utf-8')
    print(f"{'.'.join(map(str, version))} ({build}) -> {new_version} ({new_build})")


if __name__ == '__main__':
    main(sys.argv[1:])
