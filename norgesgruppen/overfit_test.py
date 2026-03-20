"""
NM i AI 2026 — Overfitting Test (Karpathy steg 3)
If the model can't overfit a single batch, you have a bug.
"""
from ultralytics import YOLO

def main():
    print("=== OVERFITTING TEST ===")
    print("Trener 50 epochs på hele treningssettet med lav oppløsning")
    print("Forventet: mAP50 > 0.5 — ellers er det en bug i datapipelinen")

    model = YOLO('yolov8n.pt')  # Nano for rask test

    model.train(
        data='dataset.yaml',
        epochs=50,
        imgsz=640,
        batch=16,
        device=0,
        augment=False,  # Ingen augmentering for overfitting-test
        patience=0,     # Ikke stopp tidlig
        name='overfit_test',
        verbose=True
    )

    print("\n=== OVERFIT TEST FERDIG ===")
    print("Sjekk mAP50 i output ovenfor.")
    print("Hvis mAP50 > 0.5: Data pipeline OK — klar for full trening")
    print("Hvis mAP50 < 0.5: BUG i konvertering — sjekk convert_coco.py")

if __name__ == "__main__":
    main()
