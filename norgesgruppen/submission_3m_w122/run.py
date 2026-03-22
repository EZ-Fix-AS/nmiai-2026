"""
NM i AI 2026 — NorgesGruppen Object Detection
3-Model WBF — weights=[1,2,2], iou_thr=0.5, rest identical to 0.8993 baseline
sandbox-safe (no os, sys, subprocess)
"""
import argparse
import json
from pathlib import Path
import numpy as np
from PIL import Image
from ultralytics import YOLO
from ensemble_boxes import weighted_boxes_fusion

CONF_THRESHOLD = 0.01
IOU_WBF = 0.5

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--input', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()

    model_dir = Path(__file__).parent
    models = [
        (YOLO(str(model_dir / 'phase1_640.onnx'), task='detect'), 640),
        (YOLO(str(model_dir / 'phase2_1280.onnx'), task='detect'), 1280),
        (YOLO(str(model_dir / 'v3_1280.onnx'), task='detect'), 1280),
    ]
    weights = [1, 2, 2]

    images = sorted(list(Path(args.input).glob('*.jpg')) + list(Path(args.input).glob('*.jpeg')))

    if not images:
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        with open(args.output, 'w') as f:
            json.dump([], f)
        return

    all_preds = []

    for img_path in images:
        image_id = int(img_path.stem.split('_')[1])
        img = Image.open(img_path)
        img_w, img_h = img.size

        boxes_list, scores_list, labels_list = [], [], []

        for model, imgsz in models:
            results = model.predict(
                source=str(img_path),
                conf=CONF_THRESHOLD,
                iou=0.45,
                imgsz=imgsz,
                device=0,
                augment=False,
                verbose=False
            )

            boxes, scores, labels = [], [], []
            for r in results:
                if r.boxes is None:
                    continue
                for i in range(len(r.boxes)):
                    x1, y1, x2, y2 = r.boxes.xyxy[i].tolist()
                    boxes.append([max(0, x1/img_w), max(0, y1/img_h), min(1, x2/img_w), min(1, y2/img_h)])
                    scores.append(float(r.boxes.conf[i].item()))
                    labels.append(int(r.boxes.cls[i].item()))

            if boxes:
                boxes_list.append(boxes)
                scores_list.append(scores)
                labels_list.append(labels)
            else:
                boxes_list.append([[0, 0, 0, 0]])
                scores_list.append([0])
                labels_list.append([0])

        fused_boxes, fused_scores, fused_labels = weighted_boxes_fusion(
            boxes_list, scores_list, labels_list,
            weights=weights, iou_thr=IOU_WBF, skip_box_thr=CONF_THRESHOLD
        )

        for box, score, label in zip(fused_boxes, fused_scores, fused_labels):
            x1, y1 = box[0] * img_w, box[1] * img_h
            x2, y2 = box[2] * img_w, box[3] * img_h
            all_preds.append({
                "image_id": image_id,
                "category_id": int(label),
                "bbox": [round(x1, 1), round(y1, 1), round(x2-x1, 1), round(y2-y1, 1)],
                "score": round(float(score), 4)
            })

    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    with open(args.output, 'w') as f:
        json.dump(all_preds, f)
    print(f"OK: {len(all_preds)} preds for {len(images)} images (3m w=[1,2,2])")

if __name__ == '__main__':
    main()
