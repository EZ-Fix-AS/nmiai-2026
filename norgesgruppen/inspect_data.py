"""
NM i AI 2026 — NorgesGruppen Data Inspection
Karpathy steg 1: Bli ett med dataene FØR du trener.
"""
import json
from collections import Counter
from pathlib import Path

def main():
    # Last COCO annotations
    ann_files = list(Path("dataset").rglob("*.json"))
    print(f"Fant {len(ann_files)} JSON-filer:")
    for f in ann_files:
        print(f"  {f} ({f.stat().st_size / 1024 / 1024:.1f} MB)")

    if not ann_files:
        print("FEIL: Ingen annotations funnet! Sjekk at dataset/ er riktig utpakket.")
        return

    # Bruk den største JSON-filen (sannsynligvis annotations)
    ann_file = max(ann_files, key=lambda f: f.stat().st_size)
    print(f"\nBruker: {ann_file}")

    with open(ann_file) as f:
        coco = json.load(f)

    print(f"\nNøkler: {list(coco.keys())}")
    print(f"Bilder: {len(coco.get('images', []))}")
    print(f"Annotasjoner: {len(coco.get('annotations', []))}")
    print(f"Kategorier: {len(coco.get('categories', []))}")

    # Klasse-distribusjon
    if 'annotations' in coco:
        cat_counts = Counter(a['category_id'] for a in coco['annotations'])
        print(f"\nKlasse-distribusjon (top 20):")
        for cat_id, count in cat_counts.most_common(20):
            cat_name = next((c['name'] for c in coco.get('categories', []) if c['id'] == cat_id), f"ID_{cat_id}")
            print(f"  [{cat_id}] {cat_name}: {count}")

        print(f"\nKlasser med <5 annotasjoner: {sum(1 for c in cat_counts.values() if c < 5)}")
        print(f"Klasser med <10 annotasjoner: {sum(1 for c in cat_counts.values() if c < 10)}")

    # Bildestørrelser
    if 'images' in coco:
        sizes = [(img['width'], img['height']) for img in coco['images']]
        size_counts = Counter(sizes)
        print(f"\nBildestørrelser:")
        for (w, h), count in size_counts.most_common(5):
            print(f"  {w}x{h}: {count} bilder")

    # Box-størrelse distribusjon
    if 'annotations' in coco:
        areas = [a['bbox'][2] * a['bbox'][3] for a in coco['annotations'] if 'bbox' in a]
        if areas:
            small = sum(1 for a in areas if a < 32*32)
            medium = sum(1 for a in areas if 32*32 <= a < 96*96)
            large = sum(1 for a in areas if a >= 96*96)
            print(f"\nBox-størrelse fordeling:")
            print(f"  Small (<32²): {small} ({small/len(areas)*100:.1f}%)")
            print(f"  Medium (32²-96²): {medium} ({medium/len(areas)*100:.1f}%)")
            print(f"  Large (>96²): {large} ({large/len(areas)*100:.1f}%)")

    # Bilder i mappen
    img_dir = Path("dataset")
    img_files = list(img_dir.rglob("*.jpg")) + list(img_dir.rglob("*.png"))
    print(f"\nBildefiler funnet: {len(img_files)}")
    if img_files:
        print(f"Eksempel: {img_files[0]}")

if __name__ == "__main__":
    main()
