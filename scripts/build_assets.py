#!/usr/bin/env python3
"""
Asset minification script.
Requires rcssmin and rjsmin.
Usage: python scripts/build_assets.py
"""
import os
import sys

try:
    import rcssmin
    import rjsmin
except ImportError:
    print("Error: rcssmin or rjsmin not installed. Run: pip install rcssmin rjsmin")
    sys.exit(1)


def main():
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    static_dir = os.path.join(base_dir, "static")

    # Process CSS
    css_dir = os.path.join(static_dir, "css")
    for filename in os.listdir(css_dir):
        if filename.endswith(".css") and not filename.endswith(".min.css"):
            src = os.path.join(css_dir, filename)
            dest = os.path.join(css_dir, filename.replace(".css", ".min.css"))
            with open(src, "r") as f:
                content = f.read()
            minified = rcssmin.cssmin(content)
            with open(dest, "w") as f:
                f.write(minified)
            print(f"Minified {filename} -> {os.path.basename(dest)}")

    # Process JS
    js_dir = os.path.join(static_dir, "js")
    for filename in os.listdir(js_dir):
        if filename.endswith(".js") and not filename.endswith(".min.js"):
            src = os.path.join(js_dir, filename)
            dest = os.path.join(js_dir, filename.replace(".js", ".min.js"))
            with open(src, "r") as f:
                content = f.read()
            minified = rjsmin.jsmin(content)
            with open(dest, "w") as f:
                f.write(minified)
            print(f"Minified {filename} -> {os.path.basename(dest)}")


if __name__ == "__main__":
    main()
