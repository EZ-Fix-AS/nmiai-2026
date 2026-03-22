"""
NM i AI 2026 — Grid search for optimal conf/iou/max_det
Runs on kit-gpu-server against validation split
Computes: 0.7 * detection_mAP@0.5 + 0.3 * classification_mAP@0.5
"""
import json
import itertools
from pathlib import Path
from pycocotools.coco import COCO
from pycocotools.cocoeval import COCOeval
from ultralytics import YOLO
import tempfile
import copy

# Paths
MODEL_PATH = "/srv/nmiai-2026/norgesgruppen/runs/detect/phase2_1280/weights/best.onnx"
ANNO_PATH = "/srv/nmiai-2026/norgesgruppen/dataset/train/annotations.json"
VAL_DIR = Path("/srv/nmiai-2026/norgesgruppen/yolo_dataset/images/val")

# Grid search parameters
CONF_VALUES = [0.001, 0.005, 0.01, 0.02, 0.05, 0.10, 0.15, 0.20]
IOU_VALUES = [0.3, 0.4, 0.45, 0.5, 0.6, 0.7, 0.8, 0.9]
MAX_DET_VALUES = [300, 500, 1000]

def get_val_image_ids():
    """Get image IDs from val split"""
    ids = set()
    for f in VAL_DIR.iterdir():
        if f.suffix.lower() in ('.jpg', '.jpeg', '.png'):
            ids.add(int(f.stem.split('_')[1]))
    return ids

def make_val_coco_gt(anno_path, val_ids):
    """Create a COCO GT object with only val images"""
    with open(anno_path) as f:
        data = json.load(f)

    val_data = {
        'images': [img for img in data['images'] if img['id'] in val_ids],
        'annotations': [ann for ann in data['annotations'] if ann['image_id'] in val_ids],
        'categories': data['categories']
    }

    # Write temp file for COCO API
    tmp = tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False)
    json.dump(val_data, tmp)
    tmp.close()
    return COCO(tmp.name), val_data

def make_detection_only_gt(val_data):
    """Create GT where all categories are mapped to 0 (detection only)"""
    det_data = copy.deepcopy(val_data)
    # Map all categories to single category
    det_data['categories'] = [{'id': 0, 'name': 'product', 'supercategory': 'product'}]
    for ann in det_data['annotations']:
        ann['category_id'] = 0

    tmp = tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False)
    json.dump(det_data, tmp)
    tmp.close()
    return COCO(tmp.name)

def run_inference(model, conf, iou, max_det):
    """Run inference on val images and return COCO-format predictions"""
    images = sorted(VAL_DIR.glob('*.jpg')) + sorted(VAL_DIR.glob('*.jpeg'))
    preds = []

    for img in images:
        image_id = int(img.stem.split('_')[1])
        results = model.predict(
            source=str(img),
            conf=conf,
            iou=iou,
            imgsz=1280,
            max_det=max_det,
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
                    "bbox": [round(x1, 1), round(y1, 1), round(x2 - x1, 1), round(y2 - y1, 1)],
                    "score": round(float(r.boxes.conf[i].item()), 4)
                })

    return preds

def compute_map50(coco_gt, predictions, is_detection_only=False):
    """Compute mAP@0.5 using COCO eval"""
    if not predictions:
        return 0.0

    preds_for_eval = predictions
    if is_detection_only:
        preds_for_eval = copy.deepcopy(predictions)
        for p in preds_for_eval:
            p['category_id'] = 0

    tmp = tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False)
    json.dump(preds_for_eval, tmp)
    tmp.close()

    coco_dt = coco_gt.loadRes(tmp.name)
    coco_eval = COCOeval(coco_gt, coco_dt, 'bbox')
    coco_eval.params.iouThrs = [0.5]  # Only IoU=0.5
    coco_eval.params.maxDets = [100, 300, 1000]
    coco_eval.evaluate()
    coco_eval.accumulate()
    coco_eval.summarize()

    # mAP@0.5 is the first value
    return coco_eval.stats[0]

def main():
    print("Loading model...")
    model = YOLO(MODEL_PATH, task='detect')

    print("Preparing validation data...")
    val_ids = get_val_image_ids()
    print(f"Val images: {len(val_ids)}")

    coco_gt_cls, val_data = make_val_coco_gt(ANNO_PATH, val_ids)
    coco_gt_det = make_detection_only_gt(val_data)

    results = []
    total = len(CONF_VALUES) * len(IOU_VALUES) * len(MAX_DET_VALUES)
    count = 0

    # Cache predictions per (conf, iou, max_det) combo
    for conf in CONF_VALUES:
        for iou in IOU_VALUES:
            for max_det in MAX_DET_VALUES:
                count += 1
                print(f"\n[{count}/{total}] conf={conf}, iou={iou}, max_det={max_det}")

                preds = run_inference(model, conf, iou, max_det)
                n_preds = len(preds)

                if n_preds == 0:
                    print(f"  No predictions, skipping")
                    results.append({
                        'conf': conf, 'iou': iou, 'max_det': max_det,
                        'det_map': 0.0, 'cls_map': 0.0, 'score': 0.0, 'n_preds': 0
                    })
                    continue

                try:
                    det_map = compute_map50(coco_gt_det, preds, is_detection_only=True)
                except Exception as e:
                    print(f"  Detection mAP error: {e}")
                    det_map = 0.0

                try:
                    cls_map = compute_map50(coco_gt_cls, preds, is_detection_only=False)
                except Exception as e:
                    print(f"  Classification mAP error: {e}")
                    cls_map = 0.0

                score = 0.7 * det_map + 0.3 * cls_map
                print(f"  det_mAP={det_map:.4f}, cls_mAP={cls_map:.4f}, SCORE={score:.4f}, preds={n_preds}")

                results.append({
                    'conf': conf, 'iou': iou, 'max_det': max_det,
                    'det_map': round(det_map, 4), 'cls_map': round(cls_map, 4),
                    'score': round(score, 4), 'n_preds': n_preds
                })

    # Sort by score
    results.sort(key=lambda x: x['score'], reverse=True)

    print("\n" + "=" * 80)
    print("TOP 20 RESULTS")
    print("=" * 80)
    print(f"{'Rank':>4} {'conf':>6} {'iou':>5} {'max_det':>7} {'det_mAP':>8} {'cls_mAP':>8} {'SCORE':>8} {'preds':>7}")
    print("-" * 80)
    for i, r in enumerate(results[:20]):
        print(f"{i+1:>4} {r['conf']:>6} {r['iou']:>5} {r['max_det']:>7} {r['det_map']:>8.4f} {r['cls_map']:>8.4f} {r['score']:>8.4f} {r['n_preds']:>7}")

    # Save full results
    with open('/srv/nmiai-2026/norgesgruppen/grid_search_results.json', 'w') as f:
        json.dump(results, f, indent=2)
    print(f"\nFull results saved to grid_search_results.json")

if __name__ == '__main__':
    main()
