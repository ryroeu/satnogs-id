"""Build the satnogs-id Doppler dataset and (optionally) push it to the HF Hub. Default: save
locally only. Pass --push (with HUGGING_FACE_HUB_TOKEN or HF_TOKEN in the env) to publish --
mirroring satnogs-signal's build_and_push. Run in-container:
    docker compose run --rm app python scripts/build_and_push.py --dataset _eval/geoscan
    docker compose run --rm app python scripts/build_and_push.py --cluster geoscan --push
"""

from __future__ import annotations
import argparse
import os
import sys
from pathlib import Path

from huggingface_hub import HfApi

from satnogs_id.data.build import CLUSTERS, harvest
from satnogs_id.data.dataset import Dataset, manifest_from_dir
from satnogs_id.data.publish import REPO_ID, build_records, push, to_hf_dataset


def main() -> None:
    """Build the dataset from one or more clusters, save it, and optionally publish to the Hub."""
    ap = argparse.ArgumentParser(
        description="Build + optionally publish the satnogs-id Doppler dataset."
    )
    ap.add_argument(
        "--cluster",
        nargs="+",
        choices=sorted(CLUSTERS),
        default=["geoscan"],
        help="one or more clusters to include",
    )
    ap.add_argument(
        "--dataset",
        nargs="*",
        default=[],
        help="existing harvested dataset dir(s), positionally parallel to --cluster",
    )
    ap.add_argument("--out", default="_dataset_build/satnogs-id-doppler")
    ap.add_argument(
        "--push", action="store_true", help="publish to the HF Hub (needs a token)"
    )
    ap.add_argument(
        "--public", action="store_true", help="make the dataset public after pushing"
    )
    ap.add_argument(
        "--card",
        default="scripts/dataset_card.md",
        help="dataset card (README) to upload",
    )
    args = ap.parse_args()

    records: list = []
    for i, cluster in enumerate(args.cluster):
        names = CLUSTERS[cluster]["truth"]
        if i < len(args.dataset):
            d = Path(args.dataset[i])
            ds = (
                Dataset.load(d)
                if (d / "manifest.json").exists()
                else manifest_from_dir(d)
            )
        else:
            ds = harvest(cluster, f"{args.out}_raw_{cluster}")
        recs = build_records(ds, names)
        records += recs
        print(f"{cluster}: {len(recs)} records")

    hf = to_hf_dataset(records)
    print(f"{hf.num_rows} total rows across {len(args.cluster)} cluster(s)")
    hf.save_to_disk(args.out)
    print(f"saved dataset to ./{args.out}/")

    if args.push:
        if not (os.environ.get("HF_TOKEN") or os.environ.get("HUGGING_FACE_HUB_TOKEN")):
            print(
                "ERROR: no HF token in env. Add HUGGING_FACE_HUB_TOKEN to .env and re-run "
                "with --push.",
                file=sys.stderr,
            )
            sys.exit(1)
        print(f"pushing to the Hub: {REPO_ID}...")
        push(hf)
        print("pushed.")

        api = HfApi()
        card = Path(args.card)
        if card.exists():
            api.upload_file(
                path_or_fileobj=str(card),
                path_in_repo="README.md",
                repo_id=REPO_ID,
                repo_type="dataset",
            )
            print(f"uploaded dataset card from {card}")
        if args.public:
            api.update_repo_settings(REPO_ID, repo_type="dataset", private=False)
            print("set dataset visibility: public")
    else:
        print("(not pushed -- re-run with --push once a HF token is set)")


if __name__ == "__main__":
    main()
