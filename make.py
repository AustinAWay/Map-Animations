"""
make — render the US map outputs.

    python make.py            # static PNG + interactive HTML preview
    python make.py --mp4      # also render the final MP4

Outputs land in ./output.
"""

import argparse
import os

import matplotlib.pyplot as plt

import geomap as gm
import scene


def render_still(path):
    fig = plt.figure(figsize=(11, 7), dpi=110)
    fig.patch.set_facecolor("white")
    ax = fig.add_axes([0, 0, 1, 1])
    scene.build_static(ax)
    fig.savefig(path, dpi=110, facecolor="white")
    plt.close(fig)
    return path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mp4", action="store_true", help="also render final MP4")
    ap.add_argument("--frames", type=int, default=72)
    args = ap.parse_args()

    out = gm.OUTPUT_DIR
    print("still ->", render_still(os.path.join(out, "us_map.png")))

    fig, anim = scene.make_animation(frames=args.frames)
    print("html  ->", scene.export_html(anim, os.path.join(out, "us_build.html")))
    if args.mp4:
        print("mp4   ->", scene.export_mp4(anim, os.path.join(out, "us_build.mp4")))
    plt.close(fig)


if __name__ == "__main__":
    main()
