"""
NM i AI 2026 — COCO → YOLO Format Conversion
"""
import json
import shutil
from pathlib import Path

def main():
    # Find annotations file
    ann_files = list(Path("dataset").rglob("*.json"))
    if not ann_files:
        print("FEIL: Ingen annotations funnet!")
        return

    ann_file = max(ann_files, key=lambda f: f.stat().st_size)
    print(f"Bruker: {ann_file}")

    with open(ann_file) as f:
        coco = json.load(f)

    images = {img['id']: img for img in coco['images']}
    categories = {cat['id']: i for i, cat in enumerate(coco['categories'])}

    print(f"Kategorier: {len(categories)}")
    print(f"Bilder: {len(images)}")
    print(f"Annotasjoner: {len(coco['annotations'])}")

    # Create YOLO directory structure
    yolo_dir = Path("yolo_dataset")
    for split in ["train", "val"]:
        (yolo_dir / "images" / split).mkdir(parents=True, exist_ok=True)
        (yolo_dir / "labels" / split).mkdir(parents=True, exist_ok=True)

    # Group annotations by image
    img_anns = {}
    for ann in coco['annotations']:
        img_id = ann['image_id']
        if img_id not in img_anns:
            img_anns[img_id] = []
        img_anns[img_id].append(ann)

    # Split: 90% train, 10% val
    img_ids = sorted(images.keys())
    split_idx = int(len(img_ids) * 0.9)
    train_ids = set(img_ids[:split_idx])
    val_ids = set(img_ids[split_idx:])

    print(f"Train: {len(train_ids)}, Val: {len(val_ids)}")

    # Find image directory
    img_dirs = [d for d in Path("dataset").rglob("*") if d.is_dir() and any(d.glob("*.jpg"))]
    if not img_dirs:
        img_dirs = [d for d in Path("dataset").rglob("*") if d.is_dir() and any(d.glob("*.png"))]

    if not img_dirs:
        print("FEIL: Ingen bildemappe funnet!")
        return

    img_source = img_dirs[0]
    print(f"Bilder fra: {img_source}")

    converted = 0
    for img_id, img_info in images.items():
        split = "train" if img_id in train_ids else "val"
        w, h = img_info['width'], img_info['height']

        # Copy image
        fname = img_info['file_name']
        src = img_source / Path(fname).name
        if not src.exists():
            # Try finding by ID
            for ext in ['.jpg', '.png']:
                alt = img_source / f"{img_id}{ext}"
                if alt.exists():
                    src = alt
                    break

        if src.exists():
            dst = yolo_dir / "images" / split / src.name
            if not dst.exists():
                shutil.copy2(src, dst)

        # Write YOLO labels
        if img_id in img_anns:
            label_name = Path(fname).stem + ".txt"
            label_path = yolo_dir / "labels" / split / label_name

            with open(label_path, 'w') as lf:
                for ann in img_anns[img_id]:
                    cat_idx = categories.get(ann['category_id'])
                    if cat_idx is None: continue

                    bx, by, bw, bh = ann['bbox']
                    # COCO (x,y,w,h) → YOLO (cx,cy,w,h) normalized
                    cx = (bx + bw/2) / w
                    cy = (by + bh/2) / h
                    nw = bw / w
                    nh = bh / h

                    # Clamp
                    cx = max(0, min(1, cx))
                    cy = max(0, min(1, cy))
                    nw = max(0.001, min(1, nw))
                    nh = max(0.001, min(1, nh))

                    lf.write(f"{cat_idx} {cx:.6f} {cy:.6f} {nw:.6f} {nh:.6f}\n")
            converted += 1

    print(f"Konvertert {converted} bilder med labels")

    # Create dataset.yaml
    cat_names = [cat['name'] for cat in sorted(coco['categories'], key=lambda c: categories[c['id']])]

    yaml_content = f"""path: {yolo_dir.resolve()}
train: images/train
val: images/val

nc: {len(categories)}
names: {cat_names}
"""

    with open("dataset.yaml", 'w') as f:
        f.write(yaml_content)

    print(f"\ndataset.yaml skrevet med {len(categories)} klasser")
    print("Klar for trening!")

if __name__ == "__main__":
    main()
