# Fall detection model benchmark

Status: draft · Date: 2026-10-24

## Problem

FallGuard's detection quality is not good enough, and we have no data to say why or what to use instead. The current pipeline in `Fall detection/fallguard/detector.py` is two-stage: `yolo11s.pt` finds people (`conf=0.3`, `imgsz=704`), each person is square-cropped (`square_crop`, 10% margin), and `leeyunjai-falldetect-11x.pt` (a YOLO detector with a `fall` class) scores the crop. `FallTracker` in `fallguard/cctv.py` raises an alert when the score is at least the threshold (default 0.4) on 3 consecutive inferences spanning at least 5 s. Neither weight file is on this machine, and no test set exists.

## Goals

1. Build a final test set: 10–15 fall clips (camera/CCTV viewpoint preferred) plus about 5 non-fall clips with poses that are easy to confuse (lying on a bed, sitting down fast, bending to pick something up). Every clip gets a time-interval ground truth label.
2. Find 5–6 candidate stage-2 "pose/fall classifier" models on Hugging Face, Kaggle, GitHub or Roboflow Universe, plus the current model as a baseline, covering three kinds:
   - `yolo-detect`: a YOLO detector with fall / no-fall classes, run on the person crop (like the current model)
   - `classify`: an image classifier (YOLO-cls, ViT, EfficientNet...) run on the crop
   - `pose`: keypoints (for example YOLO11-pose or MediaPipe) plus a rule-based or pretrained MLP/LSTM classifier
3. Evaluate each candidate as stage 2 behind the same stage 1, on frames sampled every 0.3 s, at both frame level and event level (replaying `FallTracker`), and measure latency on the RTX 3060 Laptop GPU (6 GB).
4. Write a report that ranks the candidates and recommends one pair for the project.

## Non-goals

- Changing `fallguard/` code, `requirements.txt`, the default models or the README. Swapping the model is a separate `/feature` once the user has picked one.
- Training or fine-tuning models. Only pretrained weights are evaluated.
- Changing the alert logic (threshold, number of confirmations, 5 s rule). The report may suggest new values.
- Committing videos or weights.

## Design

All new files go in `Fall detection/benchmark/`. Scripts run from `Fall detection/` with `.venv/Scripts/python -I benchmark/<script>.py` (`-I` because downloaded data is untrusted).

| File | Purpose |
|--|--|
| `benchmark/README.md` | How to install, fetch, run and read the results |
| `benchmark/requirements-benchmark.txt` | Extra packages on top of `requirements.txt`: `yt-dlp`, `huggingface_hub`, and `timm`/`mediapipe` only if a selected candidate needs them. Pinned to minor versions. |
| `benchmark/manifest.csv` | One row per clip (committed). Columns: `clip_id, source, url, license_note, start_s, end_s, is_fall, fall_start_s, fall_end_s, view, notes`. `start_s`/`end_s` trim the source; the fall times are relative to the trimmed clip. `view` ∈ `ceiling, wall, handheld, other`. |
| `benchmark/models.json` | One entry per candidate (committed): `id, kind (yolo-detect / classify / pose), source_url, files[{url, path, sha256}], fall_labels, imgsz, license, trained_on, notes`. `trained_on` lists datasets so that test-set leakage can be flagged. |
| `benchmark/fetch_clips.py` | Downloads every `manifest.csv` row into `benchmark/data/raw/` (yt-dlp with a single-file mp4 format, so ffmpeg is not needed; direct HTTP for datasets), trims with OpenCV into `benchmark/data/clips/<clip_id>.mp4`, skips existing files, and prints a summary of OK, failed and skipped clips. |
| `benchmark/fetch_models.py` | Downloads weights into `benchmark/weights/<id>/`, checks `sha256` when it is set, and prints the hash when it is empty so it can be pinned. |
| `benchmark/frames.py` | `sample_times(duration, step=0.3)`, `label_at(t, row, ignore=0.5) -> "fall" / "normal" / "ignore"`, and a frame iterator that seeks with `CAP_PROP_POS_MSEC`. |
| `benchmark/adapters.py` | One interface for every candidate: `class Stage2: name; def scores(self, crops: list[np.ndarray]) -> list[float]` (fall probability in [0, 1] per crop). One adapter per kind. A `pose` model that also finds people may implement `class SingleStage: def predict(frame) -> list[{box, fall_score}]`. |
| `benchmark/metrics.py` | Pure functions: frame metrics, threshold sweep, event replay. No model imports. |
| `benchmark/run_benchmark.py` | Main loop (below). `--models id1,id2`, `--clips`, `--step 0.3`, `--device`. |
| `benchmark/results/` | Generated CSVs (gitignored) |
| `benchmark/REPORT.md` | Final report (committed) |
| `tests/test_benchmark_metrics.py` | Offline unit tests |

Main flow in `run_benchmark.py`:

1. For each clip, sample frames at t = 0, 0.3, 0.6, … Resize so the longer side is at most 960 px (as in `fallguard/server.py`).
2. Stage 1 is fixed for every candidate: `yolo11s.pt` with the same parameters as `Detector.predict` (`classes=[0], conf=0.3, imgsz=704, max_det=12`). Crops use `fallguard.detector.square_crop`, imported and not copied. Stage-1 boxes are cached per frame so that every candidate sees the same crops.
3. Each candidate scores the crops. The frame score is the highest crop score, or 0 when no person is found.
4. Write `results/frames_<model>.csv` with `clip_id, t, label, n_persons, frame_score, stage1_ms, stage2_ms`.
5. Event replay: feed the per-person detections with `now = t` into `fallguard.cctv.FallTracker().update(dets, threshold, 3, now)`. The first `newAlert` gives the alert time.
6. Write `results/summary.csv` (one row per model) and generate the tables in `REPORT.md`.

Metrics:

- Frame level, ignoring `ignore` frames: precision, recall, F1 and accuracy at threshold 0.4, plus the best F1 and its threshold from a sweep over 0.10–0.90 in steps of 0.05. The report notes that the best threshold is tuned on the test set and is therefore optimistic.
- Event level, at threshold 0.4 and at the best threshold:
  - fall-clip recall: an alert fires at or after `fall_start_s - 0.5`
  - false-alarm clips: a non-fall clip with any alert, or a fall clip with an alert before `fall_start_s - 0.5`
  - mean detection latency: `alert_t - fall_start_s`
- Speed: mean and p95 of `stage1_ms + stage2_ms` per frame, excluding the first 5 warm-up frames, with CUDA synchronized before timing.

Recommendation rule (written into the report): among candidates with a p95 latency of 200 ms or less, pick the one with the most correct fall alerts minus false-alarm clips at threshold 0.4. Break ties by frame-level F1, then by p95 latency. Flag a candidate whose `trained_on` overlaps a test clip's source, and leave it out of the recommendation if the overlap changes the ranking.

## Data and API changes

- No change to app schemas, endpoints, env vars or `requirements.txt`.
- Add `/benchmark/data/`, `/benchmark/weights/` and `/benchmark/results/` to `Fall detection/.gitignore`. `*.mp4` and `*.pt` are already ignored.
- Baseline weights: `yolo11s.pt` comes from the Ultralytics release. `leeyunjai-falldetect-11x.pt` is searched for on Hugging Face. If it cannot be found, the report says the baseline is missing, and the benchmark still runs.

## Edge cases and errors

- **Clip download fails or the URL is gone:** log it, skip it, and continue. The report lists missing clips. Replace the row so the set still has at least 10 fall clips and at least 5 non-fall clips.
- **Fall clip too short for the 5 s rule:** a fall clip needs at least 6 s after `fall_start_s` with the person still down. Otherwise it gets `notes=short` and is counted only at frame level.
- **No person detected in a `fall` frame:** score 0, so it counts as a false negative. The report shows stage-1 recall separately: the share of fall frames with at least one person.
- **Several people in one frame:** the frame score is the highest crop score. Ground truth assumes the person who falls is the subject of the clip.
- **Candidate with odd labels** (`Fall`, `falling`, `fall_detected`, `not_fallen`...): map them explicitly with `fall_labels` in `models.json` rather than with the substring rule in `detector.py`.
- **Candidate does not load** (Ultralytics version, missing code, more than 6 GB VRAM): record `status=failed` with the reason in the summary. It does not crash the run.
- **Untrusted weights:** `.pt` files are pickles and can run code when loaded. Prefer sources with a model card and a clear origin, and safetensors or ONNX when they are offered. Pin `sha256` after the first download, and put source and license in the report.
- **Video with variable frame rate or a broken duration:** seek by milliseconds and stop when a read fails. Do not trust `CAP_PROP_FRAME_COUNT`.
- **Copyright:** clips stay local. `manifest.csv` keeps only URLs and a license note.

## Test plan

`tests/test_benchmark_metrics.py` runs offline without models:

- `test_sample_times_step` — duration 1.0 s with step 0.3 gives `[0, 0.3, 0.6, 0.9]`.
- `test_label_at_ignore_window` — with a fall at 2.0–8.0 and `ignore=0.5`: t=1.4 is normal, t=1.6 is ignore, t=2.6 is fall, t=8.6 is normal.
- `test_label_non_fall_clip` — with `is_fall=0`, every frame is normal.
- `test_frame_metrics_known_counts` — fixed TP/FP/FN/TN give exact precision, recall and F1, and `ignore` frames are excluded.
- `test_threshold_sweep_picks_best` — synthetic scores give the expected best threshold.
- `test_event_replay_alert_after_5s` — a constant 0.9 score for one person from t=2.0 at 0.3 s steps alerts at the first t with streak ≥ 3 and elapsed ≥ 5 s, using the real `FallTracker`.
- `test_event_replay_early_alert_is_false_alarm` — an alert before `fall_start_s - 0.5` counts as a false alarm.

End-to-end check: `.venv/Scripts/python -I benchmark/run_benchmark.py` over all fetched clips and models finishes with exit code 0 and writes `results/summary.csv` with one row per model, and `REPORT.md` matches it.

## Acceptance criteria

- [ ] `benchmark/manifest.csv` has 10–15 rows with `is_fall=1` and at least 5 rows with `is_fall=0`, and every row has a `url` and fall times. At least 3 fall rows are real CCTV or home-camera clips (`source` is not a lab dataset).
- [ ] `.venv/Scripts/python -I benchmark/fetch_clips.py` prints a summary in which the OK count meets the minimums above, and the files exist in `benchmark/data/clips/`.
- [ ] `benchmark/models.json` lists at least 5 stage-2 candidates plus the baseline (or the baseline is marked missing), with at least one candidate of each kind: `yolo-detect`, `classify` and `pose`. Every file has a pinned `sha256`.
- [ ] `.venv/Scripts/python -m pytest -q tests/test_benchmark_metrics.py` passes, and `.venv/Scripts/python -m pytest -q` still passes for the existing tests.
- [ ] `results/summary.csv` has these columns for every model: `model, kind, status, frame_precision, frame_recall, frame_f1, best_f1, best_threshold, fall_clips_alerted, false_alarm_clips, mean_latency_s, p95_ms, stage1_recall`.
- [ ] `benchmark/REPORT.md` contains: the clip table (source, view, labels), the candidate table (source, license, trained_on, leakage flag), the results table at threshold 0.4 and at the best threshold, a failure analysis of at least 3 example frames that fooled the top model, and one recommended model whose choice follows the recommendation rule with numbers cited.
- [ ] `git status` shows no `.mp4`, `.pt`, `.onnx` or files under `benchmark/data|weights|results`.
- [ ] `git diff --stat -- "Fall detection/fallguard" "Fall detection/requirements.txt"` is empty.

## Open questions

- Should `REPORT.md` be in English (repo convention for docs) with a Vietnamese summary for the course report, or entirely in Vietnamese?
- If no candidate meets the 200 ms p95 limit at `imgsz` 640, should a smaller input size or `yolo11n` for stage 1 also be tested?
