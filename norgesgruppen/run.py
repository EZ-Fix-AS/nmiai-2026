"""
NM i AI 2026 — NorgesGruppen Object Detection
run.py — Submission entry point with validation
"""
import argparse
import json
import sys
from pathlib import Path
from ultralytics import YOLO

CONF_THRESHOLD = 0.15

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--input', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()

    model = YOLO(str(Path(__file__).parent / 'best.pt'))
    images = sorted(Path(args.input).glob('*.jpg'))

    if not images:
        print("FEIL: Ingen bilder funnet!", file=sys.stderr)
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        with open(args.output, 'w') as f:
            json.dump([], f)
        return

    preds = []
    for img in images:
        image_id = int(img.stem.split('_')[1])

        results = model.predict(
            source=str(img),
            conf=CONF_THRESHOLD,
            iou=0.45,
            imgsz=1280,
            device=0,
            augment=True,
            verbose=False
        )

        for r in results:
            if r.boxes is None:
                continue
            for i in range(len(r.boxes)):
                x1, y1, x2, y2 = r.boxes.xyxy[i].tolist()
                preds.append({
                    "image_id": image_id,
                    "category_id": int(r.boxes.cls[i].item()),
                    "bbox": [round(x1,1), round(y1,1), round(x2-x1,1), round(y2-y1,1)],
                    "score": round(float(r.boxes.conf[i].item()), 4)
                })

    # Submission validation
    image_ids_in_preds = {p["image_id"] for p in preds}
    image_ids_expected = {int(img.stem.split('_')[1]) for img in images}
    missing = image_ids_expected - image_ids_in_preds

    if missing:
        print(f"ADVARSEL: {len(missing)} bilder har 0 prediksjoner", file=sys.stderr)

    for i, p in enumerate(preds[:5]):
        assert "image_id" in p, f"Pred {i}: mangler image_id"
        assert "category_id" in p, f"Pred {i}: mangler category_id"
        assert "bbox" in p and len(p["bbox"]) == 4, f"Pred {i}: bbox feil format"
        assert "score" in p, f"Pred {i}: mangler score"

    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    with open(args.output, 'w') as f:
        json.dump(preds, f)

    print(f"OK: {len(preds)} prediksjoner for {len(images)} bilder ({len(missing)} uten pred)")

if __name__ == '__main__':
    main()
