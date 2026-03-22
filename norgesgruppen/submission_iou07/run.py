"""
NM i AI 2026 — NorgesGruppen Object Detection
run.py for ONNX model — sandbox-safe (no os, sys, subprocess)
conf=0.01 + iou=0.7 — relaxed NMS for dense shelves
"""
import argparse
import json
from pathlib import Path
from ultralytics import YOLO

CONF_THRESHOLD = 0.01
IOU_THRESHOLD = 0.7

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--input', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()

    # ONNX model — works with any ultralytics version
    model = YOLO(str(Path(__file__).parent / 'best.onnx'), task='detect')
    images = sorted(Path(args.input).glob('*.jpg'))

    if not images:
        print("FEIL: Ingen bilder funnet!")
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
            iou=IOU_THRESHOLD,
            imgsz=1280,
            device=0,
            augment=False,
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

    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    with open(args.output, 'w') as f:
        json.dump(preds, f)

    print(f"OK: {len(preds)} prediksjoner for {len(images)} bilder")

if __name__ == '__main__':
    main()
