# CLAUDE CODE PROMPT — AGENT 2: NORGESGRUPPEN OBJECT DETECTION (V3)
# NM i AI 2026 | Dream Team: Karpathy, Howard, Li, Hotz
# V3-forbedringer: 2-fase trening (ikke 3), submission-validering, conf-threshold testing

---

## V3-ENDRINGER FRA V2

1. **2-fase progressive resizing** (ikke 3) — reduserer risiko for krasj over natten
2. **Submission-validering i run.py** — fanger formatfeil før upload
3. **Test med conf=0.10 OG conf=0.20** — bruk 2 av 3 submissions på dette
4. **Resten er uendret** — Karpathys oppskrift, Howards transfer learning, Lis datainspeksjon

---

## OPERATIVE REGLER (uendret fra V2)

**Li:** Data først. Inspiser FØR du trener.
**Karpathy:** Start enkelt. Overfit-test. Verifiser hvert steg.
**Howard:** Transfer learning. Progressive resizing. Mixup. TTA.
**Hotz:** 30 min uten fremgang → bytt tilnærming.

---

## IMPLEMENTASJON

### Steg 1: Datainspeksjon (uendret — se V2)
Kjør inspect_data.py FØRST. Ikke hopp over.

### Steg 2: COCO → YOLO konvertering (uendret — se V2)
Kjør convert_coco.py. Visuelt verifiser 5 bilder.

### Steg 3: Overfitting-test (uendret — se V2)
Kjør overfit_test.py. Hvis mAP50 < 0.5 → bug i konvertering.

### Steg 4: Trening — 2 FASER (V3-endring)

```python
"""
V3 treningsscript — 2 faser istedenfor 3
Fase 1: Rask baseline ved lav oppløsning
Fase 2: Full oppløsning finjustering

Hvis fase 2 krasjer over natten → fase 1 er backup.
"""
from ultralytics import YOLO

# === FASE 1: Lav oppløsning — rask, robust baseline ===
print("=== FASE 1: 80 epochs @ imgsz=640 ===")
model = YOLO('yolov8x.pt')

model.train(
    data='dataset.yaml',
    epochs=80,
    imgsz=640,
    batch=8,
    device=0,
    augment=True,
    mosaic=1.0,
    mixup=0.15,
    cos_lr=True,
    lr0=0.01,
    lrf=0.01,
    warmup_epochs=3,
    close_mosaic=15,
    patience=25,
    save=True,
    save_period=20,
    name='phase1_640',
    verbose=True
)

print("Fase 1 ferdig. Fase 2 starter — hvis dette krasjer, bruk phase1 som backup.")

# === FASE 2: Full oppløsning — finjustering ===
print("=== FASE 2: 70 epochs @ imgsz=1280 ===")
model = YOLO('runs/detect/phase1_640/weights/best.pt')

model.train(
    data='dataset.yaml',
    epochs=70,
    imgsz=1280,
    batch=2,            # Lav batch for stor oppløsning
    device=0,
    augment=True,
    mosaic=0.5,         # Redusert for finjustering
    mixup=0.05,
    cos_lr=True,
    lr0=0.003,          # Lavere LR for fase 2
    lrf=0.001,
    close_mosaic=10,
    patience=15,
    save=True,
    save_period=15,
    name='phase2_1280',
    verbose=True
)

print("Trening komplett!")
print("Beste modell: runs/detect/phase2_1280/weights/best.pt")
print("Backup:       runs/detect/phase1_640/weights/best.pt")
```

### Steg 5: run.py MED submission-validering (V3-endring)

```python
"""
NM i AI 2026 — NorgesGruppen Object Detection
run.py — V3 med submission-validering og konfigurerbar conf-threshold
"""
import argparse
import json
import sys
from pathlib import Path
from ultralytics import YOLO

# V3: Konfigurerbar confidence threshold
# Test med 0.10 og 0.20 på separate submissions
CONF_THRESHOLD = 0.15  # Kompromiss — juster basert på resultater

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--input', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()

    model = YOLO(str(Path(__file__).parent / 'best.pt'))
    images = sorted(Path(args.input).glob('*.jpg'))

    if not images:
        print("FEIL: Ingen bilder funnet!", file=sys.stderr)
        # V3: Skriv tom liste — bedre enn å krasje
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
            augment=True,     # Howard: TTA
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

    # === V3: SUBMISSION-VALIDERING ===
    # Fang dumme feil FØR submission
    image_ids_in_preds = {p["image_id"] for p in preds}
    image_ids_expected = {int(img.stem.split('_')[1]) for img in images}
    missing = image_ids_expected - image_ids_in_preds
    
    if missing:
        print(f"ADVARSEL: {len(missing)} bilder har 0 prediksjoner: {sorted(missing)[:10]}...", file=sys.stderr)
    
    # Sjekk format
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
```

### Steg 6: Pakk og submit (uendret fra V2)

```bash
mkdir -p submission
cp run.py submission/
cp runs/detect/phase2_1280/weights/best.pt submission/best.pt
# Hvis fase 2 krasjet: cp runs/detect/phase1_640/weights/best.pt submission/best.pt

cd submission && zip -r ../submission.zip . -x ".*" && cd ..
unzip -l submission.zip | head  # Verifiser: run.py i root
```

### Submission-strategi (3 stk)
1. **Submit 1** (lørdag morgen): Fase 2 modell, conf=0.15
2. **Submit 2** (lørdag kveld): Samme modell, conf=0.10 (test recall)
3. **Submit 3** (søndag morgen): Beste conf basert på submit 1 vs 2

---

## SUKSESSKRITERIER (V3)

- [ ] Datainspeksjon utført (Li + Karpathy)
- [ ] Overfitting-test bestått (Karpathy)
- [ ] 2-fase progressive resizing (Howard — forenklet)
- [ ] Submission-validering i run.py (V3)
- [ ] Testet med 2 ulike conf-thresholds (V3)
- [ ] run.py i ROOT av zip
- [ ] Backup-modell fra fase 1 tilgjengelig
