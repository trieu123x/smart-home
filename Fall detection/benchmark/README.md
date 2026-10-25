# Fall model benchmark

Offline comparison of fall-detection pipelines: stage-2 fall models behind FallGuard's stage-1 person
detector (`yolo11s.pt`, same parameters as `Detector.predict`), plus benchmark-only stage-1 and tracker
variants. Nothing here changes `fallguard/`; adopting a model or variant is a separate change.

The benchmark measures FallGuard as of commit `01c3556`. Commit `2638a55` later replaced the tracker and the crop
classifier with a Pose + BiLSTM pipeline, so the production pieces the benchmark uses (`FallTracker`, `iou`,
`square_crop`, `select_device`) are frozen verbatim in `legacy.py`, and nothing here imports `fallguard/`. A test
checks that. The new pipeline is not benchmarked.

Specs (repo root): `docs/specs/2026-10-24-fall-model-benchmark.md` (v1), `docs/specs/2026-10-24-fall-model-benchmark-v2.md`
(v2) and `docs/specs/2026-10-24-fall-model-benchmark-v3.md` (v3: 4 more candidates from Kaggle and Hugging Face).
Results: [REPORT.md](REPORT.md).

A pipeline is `<stage2>|s1=<variant>|trk=<variant>`:

| Part | Variants |
|--|--|
| stage 1 | `prod` = `yolo11s` conf 0.3 (production); `lowconf` = `yolo11s` conf 0.1; `pose` = `yolo11s-pose` person boxes conf 0.3 (the `pose-rule-yolo11s` weights) |
| stage 2 | the 10 candidates in `models.json` |
| tracker | `prod` = `legacy.FallTracker` (production at `01c3556`); `gap1` / `gap2` = `metrics.GapTolerantTracker`, which keeps an unmatched track for 1 / 2 inferences without resetting `fall_since` (an unmatched track is never positive and never alerts) |

## Install

From `Fall detection/`, after `START_WINDOWS.bat` (or the manual venv + `fallguard.torch_setup`) has created `.venv`:

```
.venv/Scripts/python -m pip install -r benchmark/requirements-benchmark.txt
```

## Run

All scripts run from `Fall detection/` with `-I` (isolated mode), because the downloaded videos and
weights are untrusted data:

```
.venv/Scripts/python -I benchmark/fetch_clips.py      # -> benchmark/data/clips/<clip_id>.mp4
.venv/Scripts/python -I benchmark/fetch_models.py     # -> benchmark/weights/<id>/..., checks sha256
.venv/Scripts/python -I benchmark/run_benchmark.py --stage1-variants prod,lowconf,pose --latency-runs 5
.venv/Scripts/python -I benchmark/contact_sheet.py --source youtube --step 0.5   # label check sheets
```

Useful options:

- `run_benchmark.py --models id1,id2 --clips c1,c2 --step 0.3 --device auto|cpu|cuda:0`
- `run_benchmark.py --stage1-variants prod`: only some stage-1 variants (default: all three, run one after another).
- `run_benchmark.py --latency-runs 0`: skip the latency pass. Pipelines without a median p95 are not eligible for the recommendation.
- `run_benchmark.py --report-only`: rerun the analysis (bootstrap, subsets, PR figure) and the `REPORT.md` tables
  from the CSVs in `results/`, without a GPU. Deterministic (seed 0), so a rerun gives no diff.
- `contact_sheet.py --clips c1,c2 --step 0.5`: timestamped grid per clip in `results/sheets/`, labelled fall
  interval tinted red and the ±0.5 s ignore window yellow.
- `run_benchmark.py --resume`: skip (model, stage-1 variant) pairs that are already `ok` in `results/runs.csv` and
  have a frames CSV (scoring is deterministic). They still join that variant's latency rounds. Only use it to
  continue a run on the same clip set; after a manifest change, rerun without it.
- `fetch_models.py --pin`: write the sha256 of newly downloaded files into `models.json`.
- Kaggle files (`"auth": "kaggle"` in `models.json`) need an API token in the environment, for example
  `$env:KAGGLE_API_TOKEN = '...'` in PowerShell (Kaggle → Settings → API). The token is sent only to the Kaggle
  URL, never to the storage host it redirects to, and is never written to disk.

### Running the accuracy part on Kaggle

`kaggle_bundle.py` runs the scoring on Kaggle GPUs: one private dataset and one notebook per stage-1 variant.
It needs the `kaggle` CLI in the `.venv` and a token (`KAGGLE_API_TOKEN` or `~/.kaggle`).

```
.venv/Scripts/python -I benchmark/kaggle_bundle.py bundle --user <kaggle user>   # -> benchmark/data/kaggle/
.venv/Scripts/python -I benchmark/kaggle_bundle.py push   --user <kaggle user>   # private dataset + 3 notebooks
.venv/Scripts/python -I benchmark/kaggle_bundle.py status --user <kaggle user>
.venv/Scripts/python -I benchmark/kaggle_bundle.py pull   --user <kaggle user>   # merge into results/, --report-only
```

- **What is bundled:** the benchmark code, the clips, the pinned weights, the Ultralytics wheel (the same version as
  the `.venv`, so the notebooks need no internet), and only the 4 `fallguard` modules the benchmark imports (never `.env`).
- **Latency:** the notebooks run with `--latency-runs 0`, because the 200 ms rule is about the deployment GPU.
  Measure latency locally.
- **Privacy:** keep the dataset private. The YouTube clips are noted "local research use only", and several weights
  state no license.

Unit tests (offline, no models): `.venv/Scripts/python -m pytest -q tests/test_benchmark_metrics.py`.

## Files

| File | Purpose |
|--|--|
| `manifest.csv` | One row per clip: source URL, license note, trim (`start_s`, `end_s`), `is_fall`, fall interval relative to the trimmed clip, camera `view`, `lighting` (`day` = daylight or well-lit indoor, `night` = dark scene in colour, `ir` = infrared greyscale), `notes` (`;`-separated tokens; `short` = too short for the 5 s rule, frame metrics only; `long` = long daily-life negative for false alarms per hour; `uncertain` = by-eye fall time ambiguous by > 1 s, left out of alert latency; `crop=left|right` keeps one half of a side-by-side video such as URFD's depth+RGB files). Source group: `youtube` is `real`, everything else `lab`. |
| `models.json` | `stage1`: person detectors. `candidates`: stage-2 models with `kind`, `backend`, files + pinned `sha256`, explicit `fall_labels`, `imgsz`, `license`, `trained_on`. `status: missing` keeps a row in the report without running it. |
| `frames.py` | `sample_times`, `label_at` (fall / normal / ignore within 0.5 s of an edge), seek-by-ms frame iterator. |
| `adapters.py` | `Stage2.scores(crops) -> [fall probability]`, one adapter per kind. |
| `metrics.py` | Pure metrics: frame P/R/F1, threshold sweep, tracker replay (`GapTolerantTracker`), bootstrap and paired bootstrap, AP / ROC AUC, subsets, false alarms per hour, ranking rules v1 and v2. |
| `run_benchmark.py` | Main loop, latency pass, analysis and report table generation. |
| `contact_sheet.py` | Frame grids for checking by-eye labels. |
| `legacy.py` | Frozen copy of FallGuard's `FallTracker`, `iou`, `square_crop` and `select_device` as of commit `01c3556`. |
| `render_demo.py` | Annotated demo videos of one pipeline (boxes, scores, tracker state, alerts) → `results/demo/`. |
| `kaggle_bundle.py` | Runs the scoring on Kaggle GPUs (private dataset and notebooks) and merges the results back. |
| `weights/` | Downloaded weights, gitignored except the 3 tracked files listed under "Weights in the repo". |
| `figures/pr_stage2.png` | Stage-2 PR curves under stage 1 `prod` (committed, regenerated by every run). |
| `data/`, `weights/`, `results/` | Generated, gitignored. |

## Reading the results

- `results/summary.csv`: one row per pipeline. Frame metrics at threshold 0.4, best F1 from a sweep over
  0.10–0.90 (tuned on the test set, so optimistic), event metrics from replaying the tracker variant
  (3 confirmations, 5 s) at 0.4 and at the best threshold, per-frame latency of the main pass (`mean_ms`, `p95_ms`).
  v2 columns: 95% bootstrap CIs (`*_lo`, `*_hi`; 2000 clip resamples stratified by fall / non-fall, seed 0) for
  `event_score` (alerted − false-alarm clips), `fall_recall`, `false_alarm_clips` and `frame_f1`; `ap_stage2` /
  `auc_stage2` on frames where stage 1 found a person; `fa_per_hour` (alerts on `long` clips per hour, or over all
  non-fall footage when there is none, see `fa_basis`); `p95_ms_median` from the latency pass.
- `results/latency.csv`: a fixed sample of 200 frames with a person (seed 0, round-robin over clips, drawn from the
  first stage-1 variant run), timed end to end (stage 1 + crop + stage 2) `--latency-runs` times per
  (stage-1 variant, model). The 200 ms limit applies to the median of the per-run p95.
- `results/paired.csv`: event-score and F1 differences on shared resamples. "tie" = the 95% CI includes 0.
- `results/subsets.csv`: frame recall / precision and fall clips alerted per source group, view and lighting.
- `results/runs.csv`: status per (model, stage-1 variant). `results/frames_<model>@<s1>.csv`: per-frame scores.
  `results/events_<model>@<s1>@<trk>.csv`: per-clip alerts.
- `results/failures/<model>@<s1>/`: worst false positives (`FP_*`) and false negatives (`FN_*`) with boxes and scores drawn.
- `REPORT.md`: blocks between `<!-- BEGIN GENERATED: ... -->` markers are rewritten on every run; the rest is hand-written.

## Weights in the repo

The repo tracks the weights of the recommended pipelines (force-added past `.gitignore`, sha256 pinned in `models.json`):

| File | Role | Stated license |
|--|--|--|
| `weights/yolo11s/yolo11s.pt` | stage 1 `prod` / `lowconf` | AGPL-3.0 (Ultralytics) |
| `weights/pose-rule-yolo11s/yolo11s-pose.pt` | stage 1 `pose` (recommended) | AGPL-3.0 (Ultralytics) |
| `weights/bertnardo-v8n/safeguard_best.pt` | stage 2 with no false alarms (recommended for the current pipeline) | Apache 2.0 as stated on Kaggle; an Ultralytics fine-tune, so AGPL-3.0 in practice |
| `weights/jerryg-v8x-cls/best.pt` | stage 2 of the recommended full pipeline (107 MB, **Git LFS**) | none stated by the author (JerryG-TAMU on Hugging Face) |

- **Git LFS:** `jerryg-v8x-cls/best.pt` is larger than GitHub's 100 MB limit, so it is stored with Git LFS (see `.gitattributes`).
  Install `git-lfs` before cloning, or run `git lfs pull` after cloning. Without it the file is a small pointer, and
  the sha256 check refuses to load it.
- **License:** its author states no license. Keep the repo private before sharing it outside the course team.
- **Other candidates:** `fetch_models.py` downloads them, and also this file from Hugging Face if needed. The Kaggle ones need `KAGGLE_API_TOKEN`.

## Safety

`.pt` files are pickles and can run code when loaded. Mitigations:

- Only sources with a model card and a clear origin are listed (the baseline is the one exception, kept on purpose).
- Every file has a pinned `sha256`. Downloads are hashed before they are renamed into place, and
  `run_benchmark.py` re-checks the hash right before loading. An unpinned or mismatching file is refused.
- `run_benchmark.py` sets `ULTRALYTICS_SAFE_LOAD=1` (`weights_only` loading with Ultralytics' class allow-list),
  `YOLO_AUTOINSTALL=false` and `YOLO_OFFLINE=true`.
- Downloads are HTTPS only, including redirects, and capped at 2 GiB.

Clips stay local; `manifest.csv` keeps only URLs and license notes.
