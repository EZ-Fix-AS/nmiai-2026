"""
NM i AI 2026 — V3 training with stronger augmentation
Fine-tune from phase2 best.pt with mixup, copy_paste, more aggressive scale
"""
from ultralytics import YOLO

def main():
    # Start from our best model
    model = YOLO('runs/detect/phase2_1280/weights/best.pt')

    model.train(
        data='dataset.yaml',
        epochs=50,           # Shorter — we're fine-tuning, not training from scratch
        imgsz=1280,
        batch=2,
        device=0,
        augment=True,
        mosaic=1.0,
        mixup=0.3,           # Stronger regularization
        copy_paste=0.3,      # Copy-paste for dense scenes
        scale=0.7,           # More aggressive scaling
        fliplr=0.5,
        degrees=5,           # Light rotation
        translate=0.2,
        cos_lr=True,
        lr0=0.002,           # Lower LR for fine-tuning
        lrf=0.001,
        close_mosaic=10,
        patience=15,
        save_period=10,
        name='v3_strong_aug',
        exist_ok=True,
    )

    # Export best to ONNX
    best = YOLO('runs/detect/v3_strong_aug/weights/best.pt')
    best.export(format='onnx', opset=17, imgsz=1280, simplify=True)
    print("V3 training complete + ONNX exported!")

if __name__ == '__main__':
    main()
