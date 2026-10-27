# Model files

The updated delivery ZIP includes both uploaded models, unchanged:

- `fall/best_fall_lstm.pth`: user's Kaggle BiLSTM checkpoint.
- `pose/yolo11n-pose.pt`: uploaded YOLO11n-Pose checkpoint.

These binary files are intentionally ignored by Git. After cloning the source,
create `models/fall` and `models/pose`, then copy the two model files to those
paths. Remove download suffixes such as `(1)` and `(2)` from the filenames.

The BiLSTM loader accepts the original float32 NumPy scalers and tensor scalers
with `weights_only=True`. No checkpoint conversion or retraining is needed.
The expected configuration is 32 frames, 55 features, hidden size 128,
two bidirectional LSTM layers, and classes `NORMAL`, `FALL`.

Run `CHECK_MODELS.bat` after installing the environment to test both forwards.
This uses synthetic inputs; use `TEST_VIDEO.py` for real video evaluation.

YOLO can download its official weight when absent, but the trained BiLSTM
must be supplied locally. The included files allow model loading offline
after dependencies are installed.
