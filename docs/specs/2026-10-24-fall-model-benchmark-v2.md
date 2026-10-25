# Fall model benchmark v2: larger test set and deeper evaluation

Status: draft · Date: 2026-10-24 · Builds on: `docs/specs/2026-10-24-fall-model-benchmark.md` (v1, implemented in `Fall detection/benchmark/`)

## Problem

The v1 benchmark could not separate the two top stage-2 models:
- `jerryg-v8x-cls` and the baseline `leeyunjai-11x` tie on events (4/10 alerted, 1 false alarm).
- Their frame F1 differs by 0.0009, and the order flipped after a pixel-level resize change.

Only 10 fall clips count at event level, so one clip moves recall by 10 points. Only 4 of those clips are real CCTV, which is the footage least likely to have leaked into training data.

v1 also found that most misses come from stage 1 and from `FallTracker` resetting on a single missed frame. Comparing stage-2 models alone therefore cannot pick the best pipeline.

## Goals

1. **Add 20 clips, for a total of 40.**
   - About 12 fall clips, at least 10 of them real CCTV or home-camera footage.
   - About 8 non-fall clips: at least 6 hard negatives from real footage, plus 1–2 long daily-life videos (5–10 min, no fall) to measure false alarms per hour.
2. **Report uncertainty.** Give 95% bootstrap confidence intervals for the main metrics and paired comparisons between candidates, so a tie is reported as a tie.
3. **Break results down.** Split results by source group (real vs lab), camera view and lighting. Score stage 2 alone on frames where stage 1 found a person, with a PR curve, average precision and ROC AUC.
4. **Evaluate pipeline combinations.** Variants run inside the benchmark only:
   - stage 1: production, low-confidence, or pose-model person boxes;
   - tracker: production, or tolerant of 1–2 missed frames.

   Recommend both a stage-2 model for the current pipeline and the best full pipeline.
5. **Measure latency robustly.** Repeat a fixed latency pass 5 times and report the median of p95.

## Non-goals

- Changing `fallguard/`, `requirements.txt`, the default models or the README. The tracker and stage-1 variants exist only in `benchmark/`. Adopting one is a separate `/feature`.
- Training, fine-tuning or adding new stage-2 candidates. The 6 v1 candidates are kept.
- Committing videos, weights or `benchmark/results/`.

## Design

All changes are in `Fall detection/benchmark/` and `Fall detection/tests/`. Run commands are the same as in v1.

### Data

- **`manifest.csv`**
  - Add 20 rows, keeping the v1 columns.
  - Add a `lighting` column with values `day`, `night` or `ir`, and backfill it for the v1 rows.
  - A source group is derived from `source`: `youtube` is `real`, everything else is `lab`.
  - Long negatives get the notes token `long`.
- **`contact_sheet.py` (new):** `contact_sheet.py --clips id1,id2 --step 0.5` writes `results/sheets/<clip_id>.jpg`, a timestamped grid with the labelled fall interval tinted. Every by-eye label can then be checked by a person. This replaces the scratch script used in v1.

### Pipeline variants

- **Stage 1** (`run_benchmark.py --stage1-variants prod,lowconf,pose`):
  - `prod`: `yolo11s`, conf 0.3 (as in v1).
  - `lowconf`: `yolo11s`, conf 0.1.
  - `pose`: `yolo11s-pose` boxes for class person, conf 0.3, same `imgsz` and `max_det`.

  Each variant gets its own stage-1 cache. Every stage-2 candidate is scored once per variant.
- **Tracker** (`metrics.py`, replay only):
  - `prod` is `fallguard.cctv.FallTracker`.
  - `gap1` and `gap2` are a subclass, `GapTolerantTracker(max_missing)`, defined in `benchmark/metrics.py`. A track that is unmatched for up to N consecutive inferences is kept with its `fall_since`, and `streak` is held rather than reset. An unmatched track does not count as positive and cannot raise an alert.
  - All other rules (3 confirmations, ≥ 5 s, 0.25 IoU match, 2 s inference-gap reset) are inherited.
- **Pipeline id:** `<stage2>|s1=<variant>|trk=<variant>`.
  - Frame metrics depend on stage 1 and stage 2 only.
  - Event metrics depend on all three.

### Metrics (`metrics.py`, pure)

- **`bootstrap(clip_ids, stat_fn, n=2000, seed=0)`:** resample clips with replacement, stratified by fall / non-fall, and return the point estimate and the 2.5 / 97.5 percentiles.
  - It is used for event score (alerted minus false-alarm clips), fall-clip recall, false-alarm clips and frame F1.
- **`paired_bootstrap(a, b, ...)`:** computes CIs of the difference on the same resamples.
  - The report compares the top pipeline against every other candidate in the production pipeline and against the baseline.
  - "Tie" means the 95% CI of the event-score difference includes 0.
- **`average_precision(labels, scores)` and `roc_auc(labels, scores)`:** both use the trapezoid rule and are computed on frames with `n_persons > 0` and a label other than `ignore`. This is the stage-2-only view.
- **Subset breakdown:** frame recall, frame precision and fall clips alerted per group (`real` / `lab`), per `view` and per `lighting`.
  - A subset with fewer than 3 fall clips is shown, but marked "n < 3".
- **False alarms per hour:** number of alerts on `long` clips divided by their total duration.
  - If no long clip could be fetched, compute it over all non-fall footage and flag it.

### Latency (`run_benchmark.py --latency-runs 5`)

- Draw a fixed sample of 200 frames with seed 0: frames with at least one person, spread over all clips.
- For each pipeline's stage-1 variant and stage-2 model, warm up, then time the sample 5 times with CUDA synchronized.
- Write `results/latency.csv` with columns `model, stage1, run, mean_ms, p95_ms`.
- The summary uses the median over runs of `p95_ms`. The 200 ms limit applies to that median.

### Outputs

- `results/summary.csv`: one row per pipeline. It has the v1 columns plus:
  - `stage1_variant`, `tracker`;
  - the CI columns (`*_lo`, `*_hi`) for event score, fall recall, false-alarm clips and frame F1;
  - `ap_stage2`, `auc_stage2`, `fa_per_hour`, `p95_ms_median`.
- `results/subsets.csv` and `results/paired.csv`.
- `figures/pr_stage2.png`: PR curves of the 6 stage-2 models under the `prod` stage 1. This file is small and committed.

### `REPORT.md` (Vietnamese, regenerated blocks plus a hand-written analysis)

New generated blocks:
- `results_ci`: production pipeline per candidate, with CIs;
- `paired`;
- `subsets`;
- `stage2_only`: AP, AUC and a link to the PR figure;
- `pipelines`: top 10 combinations by event score;
- `latency`.

### Recommendation rule v2 (generated and applied in the report)

1. **Eligible:** status ok and median p95 ≤ 200 ms.
2. **Stage-2 recommendation, production pipeline (`s1=prod|trk=prod`):** rank by event score at 0.4.
   - If the top two tie (paired CI includes 0), break the tie in this order: lower `fa_per_hour`, then a stated license, then lower median p95.
   - The report must say "tie" explicitly when that applies.
3. **Pipeline recommendation:** the same rule over all combinations. Report how much the best pipeline gains over the production pipeline of the same stage-2 model, with the paired CI.
4. **Leakage:** keep the v1 rule. Also re-rank on the `real` group alone and say whether the winner changes.

## Data and API changes

- No change to app schemas, endpoints, env vars or `fallguard/`.
- `manifest.csv` gains the `lighting` column, and the `long` notes token is introduced.
- `models.json` does not change. The `pose` stage-1 variant reuses the `pose-rule-yolo11s` weights through the existing pinned sha256.
- New committed file: `benchmark/figures/pr_stage2.png`.

## Edge cases and errors

- **Clips:**
  - **Dead URL or format error:** log it, skip it, and replace the row. The set must stay at ≥ 35 fetched clips, with ≥ 20 event-eligible fall clips, ≥ 10 real-CCTV fall clips and ≥ 10 non-fall clips.
  - **Video edits:** trim around cuts, zooms and replays. A clip whose fall happens only inside an edited replay is not used.
  - **Uncertain by-eye labels:** use the `ignore` window as usual. Add `notes=uncertain` when the fall moment is ambiguous by more than 1 s; those clips are excluded from latency statistics.
- **Long negatives:** process them at the same 0.3 s step. If decoding is slow, the run may take longer than the v1 run, but there is no frame cap.
- **Several people:** as in v1, the subject of the clip is assumed to be the person who falls. The tolerant tracker must not keep a track alive across a camera cut; the existing 2 s inference-gap rule and the IoU match handle this, and a unit test covers it.
- **Pose stage 1:** a frame where pose returns zero persons scores 0, the same as in v1.
- **Bootstrap with a degenerate resample** (no fall frames): treat the metric as undefined for that resample and skip it. Report how many resamples were skipped if more than 1%.
- **GPU memory:** the 3 stage-1 variants run one after another and models are unloaded between them. A failure records `status=failed` per pipeline.

## Test plan

New tests in `tests/test_benchmark_metrics.py` (offline):

- `test_gap_tracker_keeps_fall_since_over_one_miss`: a 0.9 score at 0.3 s steps with one empty frame in the middle. `gap1` alerts at the same time as an uninterrupted sequence would; `prod` alerts later or not at all.
- `test_gap_tracker_does_not_alert_on_missing_frames`: a fall followed by empty frames only. No alert fires while the track is unmatched.
- `test_gap_tracker_respects_inference_gap_reset`: a gap of more than 2 s between inferences resets even with `gap2`.
- `test_bootstrap_ci_contains_point_and_is_deterministic`: same seed, same CI; lo ≤ point ≤ hi.
- `test_paired_bootstrap_identical_models_is_zero`: the difference CI is [0, 0].
- `test_average_precision_and_auc_known_values`: hand-computed small examples, including perfect and inverted rankings.
- `test_fa_per_hour`: 2 alerts over 30 min of long clips gives 4.0.
- `test_recommend_v2_tie_breaks_on_fa_then_license_then_latency`.

End-to-end check: `.venv/Scripts/python -I benchmark/run_benchmark.py --stage1-variants prod,lowconf,pose --latency-runs 5` exits 0. It writes `summary.csv` with 6 × 3 × 3 = 54 pipeline rows, plus `subsets.csv`, `paired.csv`, `latency.csv` and `figures/pr_stage2.png`, and `REPORT.md --report-only` regenerates without diff.

## Acceptance criteria

- [ ] **Manifest:** `manifest.csv` has ≥ 40 rows.
  - ≥ 20 are fall rows without `short`.
  - ≥ 10 fall rows have `source=youtube`.
  - ≥ 10 rows are non-fall, including ≥ 1 `long` row totalling ≥ 5 min.
  - Every row has `lighting`.
- [ ] **Fetch:** `fetch_clips.py` exits 0, and its summary shows the minimums above as available.
- [ ] **Contact sheets:** `contact_sheet.py` produces a sheet for every `youtube` clip.
- [ ] **Tests:** `pytest -q tests/test_benchmark_metrics.py` passes with the new tests, and `pytest -q` passes overall.
- [ ] **Summary:** `results/summary.csv` has 54 pipeline rows with the v1 columns, the CI columns, `ap_stage2`, `auc_stage2`, `fa_per_hour` and `p95_ms_median`.
- [ ] **Latency:** `results/latency.csv` has 5 runs per (stage-1 variant, model).
- [ ] **Report:** `REPORT.md` contains:
  - the CI table;
  - the paired comparison, which states "tie" or "different" for the top pair;
  - the subset tables;
  - the stage-2-only table with the PR figure;
  - the top-10 pipeline table;
  - a stage-2 recommendation and a pipeline recommendation that follow rule v2 with numbers cited;
  - an updated failure analysis of ≥ 3 frames that fooled the recommended pipeline.
- [ ] **Git:** `git status` shows no `.mp4`, `.pt` or `.onnx` file, and nothing under `benchmark/data|weights|results`.
- [ ] **fallguard untouched:** `git diff --stat -- "Fall detection/fallguard" "Fall detection/requirements.txt"` is empty.

## Open questions

- Is committing `figures/pr_stage2.png` (about 50 KB) acceptable, or should the PR curve stay a table only?
- Long negatives: real CCTV daily-life footage of 5–10 min is hard to find on YouTube.
  - Fallback: the new non-fall clips plus the v1 non-fall clips, giving about 3 min in total.
  - Alternatively, you record one at home with the project camera. Which do you prefer?
