from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from collections import deque
from typing import Any

import cv2
import numpy as np
import torch
import torch.nn as nn


class ConvBlock(nn.Module):
    def __init__(self, in_channels: int, out_channels: int):
        super().__init__()
        self.block = nn.Sequential(
            nn.Conv2d(in_channels, out_channels, 3, padding=1, bias=False),
            nn.BatchNorm2d(out_channels),
            nn.ReLU(inplace=True),
            nn.MaxPool2d(2),
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.block(x)


class FrameCNN(nn.Module):
    def __init__(self):
        super().__init__()
        self.features = nn.Sequential(
            ConvBlock(3, 32),
            ConvBlock(32, 64),
            ConvBlock(64, 128),
            nn.Conv2d(128, 256, 3, padding=1, bias=False),
            nn.BatchNorm2d(256),
            nn.ReLU(inplace=True),
            nn.AdaptiveAvgPool2d((1, 1)),
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.features(x).flatten(1)


class AntiTheftModel(nn.Module):
    def __init__(self):
        super().__init__()
        self.cnn = FrameCNN()
        self.lstm = nn.LSTM(
            input_size=256,
            hidden_size=128,
            num_layers=2,
            batch_first=True,
            dropout=0.3,
            bidirectional=True,
        )
        self.classifier = nn.Sequential(
            nn.LayerNorm(256),
            nn.Dropout(0.5),
            nn.Linear(256, 128),
            nn.ReLU(inplace=True),
            nn.Dropout(0.3),
            nn.Linear(128, 2),
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        b, t, c, h, w = x.shape
        x = x.reshape(b * t, c, h, w)
        features = self.cnn(x)
        features = features.reshape(b, t, 256)
        sequence, _ = self.lstm(features)
        feature = sequence.mean(dim=1)
        return self.classifier(feature)


@dataclass
class AnalyzerConfig:
    img_size: int = 160
    seq_len: int = 16
    source_frame_size: int = 64
    frame_step: int = 10
    window_stride: int = 8
    threshold: float = 0.40
    inference_batch_size: int = 8


class AntiTheftAnalyzer:
    MEAN = np.array([0.485, 0.456, 0.406], dtype=np.float32)
    STD = np.array([0.229, 0.224, 0.225], dtype=np.float32)

    def __init__(self, checkpoint_path: str | Path):
        self.checkpoint_path = Path(checkpoint_path)
        if not self.checkpoint_path.exists():
            raise FileNotFoundError(f"Model not found: {self.checkpoint_path}")

        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        self.model = AntiTheftModel().to(self.device)

        checkpoint = torch.load(self.checkpoint_path, map_location=self.device)
        state_dict = checkpoint.get("model_state_dict", checkpoint)
        self.model.load_state_dict(state_dict)
        self.model.eval()

        self.epoch = checkpoint.get("epoch") if isinstance(checkpoint, dict) else None
        self.saved_threshold = checkpoint.get("threshold") if isinstance(checkpoint, dict) else None
        self.model_config = checkpoint.get("config", {}) if isinstance(checkpoint, dict) else {}

    @staticmethod
    def _letterbox(image: np.ndarray, size: int) -> np.ndarray:
        h, w = image.shape[:2]
        scale = min(size / w, size / h)
        nw = int(round(w * scale))
        nh = int(round(h * scale))
        resized = cv2.resize(image, (nw, nh), interpolation=cv2.INTER_AREA)
        canvas = np.zeros((size, size, 3), dtype=np.uint8)
        x = (size - nw) // 2
        y = (size - nh) // 2
        canvas[y : y + nh, x : x + nw] = resized
        return canvas

    def _preprocess_bgr(self, frame: np.ndarray, size: int, source_size: int) -> np.ndarray:
        """Match the frame domain used during training as closely as possible.

        The Kaggle UCF-Crime frame dataset used for training contains every 10th
        video frame pre-resized to 64x64. Training then passed those images
        through the 160x160 preprocessing pipeline. Raw MP4 inference therefore
        first reproduces that 64x64 square representation before the model input
        resize/normalization. This is intentionally different from directly
        letterboxing a full-resolution MP4 frame to 160x160.
        """
        image = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

        # Critical train/inference alignment: the training source frames are 64x64.
        image = cv2.resize(
            image,
            (source_size, source_size),
            interpolation=cv2.INTER_AREA,
        )

        image = self._letterbox(image, size)
        image = image.astype(np.float32) / 255.0
        image = (image - self.MEAN) / self.STD
        image = np.transpose(image, (2, 0, 1))
        return image.astype(np.float32)

    @torch.inference_mode()
    def _infer_batch(self, windows: list[np.ndarray]) -> np.ndarray:
        if not windows:
            return np.empty((0,), dtype=np.float32)
        arr = np.stack(windows)
        tensor = torch.from_numpy(arr).to(self.device, non_blocking=True)
        with torch.amp.autocast(
            device_type="cuda",
            enabled=self.device.type == "cuda",
        ):
            logits = self.model(tensor)
            probs = torch.softmax(logits, dim=1)[:, 1]
        return probs.float().cpu().numpy()

    def analyze_video(
        self,
        video_path: str | Path,
        *,
        frame_step: int = 10,
        window_stride: int = 8,
        threshold: float = 0.40,
        inference_batch_size: int = 8,
    ) -> dict[str, Any]:
        cfg = AnalyzerConfig(
            img_size=int(self.model_config.get("IMG_SIZE", 160)),
            seq_len=int(self.model_config.get("SEQ_LEN", 16)),
            source_frame_size=int(self.model_config.get("SOURCE_FRAME_SIZE", 64)),
            frame_step=max(1, int(frame_step)),
            window_stride=max(1, int(window_stride)),
            threshold=float(np.clip(threshold, 0.01, 0.99)),
            inference_batch_size=max(1, int(inference_batch_size)),
        )

        cap = cv2.VideoCapture(str(video_path))
        if not cap.isOpened():
            raise ValueError("Không thể mở video.")

        fps = float(cap.get(cv2.CAP_PROP_FPS) or 0.0)
        if fps <= 1e-3:
            fps = 30.0
        frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        duration = frame_count / fps if frame_count > 0 else 0.0

        frame_buffer: deque[np.ndarray] = deque(maxlen=cfg.seq_len)
        index_buffer: deque[int] = deque(maxlen=cfg.seq_len)
        pending_windows: list[np.ndarray] = []
        pending_times: list[float] = []
        results: list[dict[str, Any]] = []

        raw_index = 0
        sampled_index = 0

        def flush_pending() -> None:
            nonlocal pending_windows, pending_times, results
            if not pending_windows:
                return
            probs = self._infer_batch(pending_windows)
            for time_s, intrusion in zip(pending_times, probs):
                intrusion = float(intrusion)
                results.append(
                    {
                        "time": round(float(time_s), 2),
                        "normal": float(1.0 - intrusion),
                        "intrusion": intrusion,
                        "status": "Intrusion" if intrusion >= cfg.threshold else "Normal",
                    }
                )
            pending_windows = []
            pending_times = []

        try:
            while True:
                ok, frame = cap.read()
                if not ok:
                    break

                if raw_index % cfg.frame_step == 0:
                    processed = self._preprocess_bgr(
                        frame,
                        cfg.img_size,
                        cfg.source_frame_size,
                    )
                    frame_buffer.append(processed)
                    index_buffer.append(raw_index)

                    if (
                        len(frame_buffer) == cfg.seq_len
                        and (sampled_index - (cfg.seq_len - 1)) % cfg.window_stride == 0
                    ):
                        pending_windows.append(np.stack(list(frame_buffer)))
                        center_raw_index = list(index_buffer)[cfg.seq_len // 2]
                        pending_times.append(center_raw_index / fps)

                        if len(pending_windows) >= cfg.inference_batch_size:
                            flush_pending()

                    sampled_index += 1

                raw_index += 1
        finally:
            cap.release()

        flush_pending()

        # Very short video: pad the sampled sequence with the final frame.
        if not results and len(frame_buffer) > 0:
            frames = list(frame_buffer)
            indices = list(index_buffer)
            while len(frames) < cfg.seq_len:
                frames.append(frames[-1].copy())
                indices.append(indices[-1])
            prob = float(self._infer_batch([np.stack(frames)])[0])
            center_time = indices[min(cfg.seq_len // 2, len(indices) - 1)] / fps
            results.append(
                {
                    "time": round(float(center_time), 2),
                    "normal": float(1.0 - prob),
                    "intrusion": prob,
                    "status": "Intrusion" if prob >= cfg.threshold else "Normal",
                }
            )

        if not results:
            raise ValueError("Video không có frame hợp lệ để phân tích.")

        intrusion_values = np.array([x["intrusion"] for x in results], dtype=np.float32)
        max_intrusion = float(intrusion_values.max())
        avg_intrusion = float(intrusion_values.mean())
        alert_windows = int((intrusion_values >= cfg.threshold).sum())
        status = "Intrusion" if max_intrusion >= cfg.threshold else "Normal"

        return {
            "status": status,
            "max_intrusion": max_intrusion,
            "average_intrusion": avg_intrusion,
            "alert_windows": alert_windows,
            "total_windows": len(results),
            "threshold": cfg.threshold,
            "frame_step": cfg.frame_step,
            "window_stride": cfg.window_stride,
            "seq_len": cfg.seq_len,
            "source_frame_size": cfg.source_frame_size,
            "fps": round(fps, 3),
            "duration": round(duration, 2),
            "device": str(self.device),
            "model_epoch": self.epoch,
            "model_version": self.model_config.get("version", "antitheft_v3"),
            "windows": results,
        }
