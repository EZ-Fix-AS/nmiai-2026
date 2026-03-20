"""
NM i AI 2026 — NorgesGruppen Full Training
2-fase progressive resizing (Howard)
"""
from ultralytics import YOLO

def main():
    # === FASE 1: Lav oppløsning — rask baseline ===
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

    print("Fase 1 ferdig. Fase 2 starter...")

    # === FASE 2: Full oppløsning — finjustering ===
    print("=== FASE 2: 70 epochs @ imgsz=1280 ===")
    model = YOLO('runs/detect/phase1_640/weights/best.pt')

    model.train(
        data='dataset.yaml',
        epochs=70,
        imgsz=1280,
        batch=2,
        device=0,
        augment=True,
        mosaic=0.5,
        mixup=0.05,
        cos_lr=True,
        lr0=0.003,
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

if __name__ == "__main__":
    main()
