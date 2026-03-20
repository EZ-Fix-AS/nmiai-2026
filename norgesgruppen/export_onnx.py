"""
Eksporter YOLOv8x til ONNX for sandbox-kompatibilitet.
Kjør ETTER trening er ferdig.
Sandbox har onnxruntime-gpu 1.20.0, opset 17 er safe.
"""
from ultralytics import YOLO
from pathlib import Path

# Finn beste modell
phase2 = Path("runs/detect/phase2_1280/weights/best.pt")
phase1 = Path("runs/detect/phase1_640/weights/best.pt")

model_path = phase2 if phase2.exists() else phase1
print(f"Eksporterer: {model_path}")

model = YOLO(str(model_path))
model.export(format="onnx", opset=17, imgsz=1280, simplify=True)

onnx_path = model_path.with_suffix(".onnx")
print(f"ONNX eksportert: {onnx_path}")
print(f"Størrelse: {onnx_path.stat().st_size / 1024 / 1024:.1f} MB")
