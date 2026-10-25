# Fine-tune the recommended fall pipeline on Kaggle

Status: draft · Date: 2026-10-25 · Builds on: `docs/specs/2026-10-24-fall-model-benchmark-v3.md` (`Fall detection/benchmark/`, results in `benchmark/REPORT.md`)

## Problem

The pipeline recommended by v3 is `yolo11s-pose` (stage 1) + `jerryg-v8x-cls` (stage 2) + `gap1`. It catches 11/21 falls,
and both stages fail in known ways (REPORT.md §11):

- **Stage 1 misses people lying on the floor.** 52% of missed fall frames have no person box.
- **Stage 2 scores sitting people as fallen.** It gives a fall score to 1001/1001 frames of the classroom clip, and all
  4 sitting-children clips raise false alarms. jerryg has only `neg`/`pos` classes, trained on 564 images at 128 px.

Both models are off-the-shelf and were never trained on this domain.

## Goals

1. **Freeze a 20/20 split** of the 40 benchmark clips.
   - The split is random (seed 0), grouped, and stratified by fall / non-fall and real / lab.
   - 20 `test` clips are used only for evaluation. 20 `train` clips may be used as stage-2 training data.
2. **Fine-tune stage 1:** `yolo11s` (detect, single class `person`) on **E-FPDS**, so that it finds people lying on the floor.
3. **Fine-tune stage 2:** `jerryg-v8x-cls` to **3 classes `fall` / `sit` / `normal`** at 128 px, on crops from **CAUCAFall**
   and the **20 train clips**. Fall score = P(`fall`).
4. **Train on Kaggle:** one notebook per stage, using both T4 GPUs (DDP), ≤ 6 h each. The notebooks are built and
   pushed by a script, like `kaggle_bundle.py`.
5. **Evaluate on the 20 test clips** with the existing benchmark. The baseline (`jerryg-v8x-cls|s1=pose|trk=gap1`) is
   re-analysed on the same 20 clips.
   - **Success:** `jerryg-ft3|s1=ft|trk=gap1` has event score ≥ the baseline, false-alarm clips ≤ the baseline, and
     median p95 ≤ 200 ms on the RTX 3060 Laptop.
   - The report states met / not met with numbers and paired CIs.
   - **40-clip results:** the report also gives results on all 40 clips, in a separate section marked **contaminated**
     (20 of the clips were in stage-2 training). Only the 20-clip test result decides Goal 5.

## Non-goals

- Changing `fallguard/` or the production app (it now runs a Pose + BiLSTM pipeline, commit `2638a55`).
- Fine-tuning `yolo11s-pose` (there are no keypoint labels), or any other stage-2 candidate.
- OmniFall, Roboflow or other datasets, and manual box annotation. The 20 train clips and CAUCAFall feed stage 2 only.
- Committing training data or fine-tuned weights. The repo is public and the base weights are unlicensed. Committing
  them needs a separate decision.
- Retraining on the test clips, or tuning on them: no threshold or epoch choice may look at the test split.

## Design

New package `Fall detection/benchmark/finetune/`. Scripts run from `Fall detection/` with `.venv/Scripts/python -I`.

### Split: `finetune/make_split.py` → `benchmark/split.csv` (committed)

- **Columns:** `clip_id, group, split`.
- **Groups:** clips that share a person or a scene go to the same side.
  - GMDCSA-24 by subject (`gmd_s1_*`, `gmd_s2_*` …).
  - URFD as one group.
  - `yt_neg_kids_floor1..3` and `yt_long_class1` as one group (the same school).
  - Every other YouTube clip is its own group.
- **Assignment:** seed 0, chosen from 1000 random group assignments as the one closest to 10/10 on each of
  (fall, non-fall) × (real, lab).
- **Requirements:**
  - The `test` side gets ≥ 8 event-eligible fall clips.
  - The `long` clip goes to `test`, so false alarms per hour stay measurable.
  - The script fails if no assignment meets these.

### Stage-1 data: `finetune/prepare_stage1.py`

- **Download:** E-FPDS from the official page (https://gram.web.uah.es/data/datasets/fpds/) into `benchmark/data/efpds/`.
  The page states no license. It is used for research only in this university course project; the user deletes the
  project after the course. The README cites Maldonado-Bascón et al., Electronics 2019.
- **Convert to YOLO format** with one class `person`, mapping every E-FPDS box class to it.
  - The converter checks the annotation format it finds and stops with a clear message if the format is unknown.
- **Keep other people labelled (teacher merge).** Boxes of `yolo11s` with conf ≥ 0.5 that overlap no E-FPDS box
  (IoU < 0.5) are added as `person`. Otherwise people that E-FPDS leaves unlabelled would teach the model to ignore them.
- **Leakage filter:** compute a dHash of every image and of frames of all 40 benchmark clips sampled every 0.5 s.
  Drop images within Hamming distance ≤ 6 of any clip frame, and log the count.
- **Validation:** use E-FPDS's own split if it has one, else 10% of images grouped by source sequence.
- **Output:** `benchmark/data/finetune/stage1/` (`images/`, `labels/`, `data.yaml`).

### Stage-2 data: `finetune/build_stage2_crops.py`

- **Crop function:** crops are cut with `legacy.square_crop` (10% margin), the same as in the benchmark, into an
  ImageFolder `benchmark/data/finetune/stage2/{train,val}/{fall,sit,normal}/`.
- **Person boxes:** from `yolo11s-pose` at conf 0.3 (the benchmark `pose` stage 1).
- **CAUCAFall** (CC BY 4.0, https://data.mendeley.com/datasets/7w7fccy7ky/4):
  - Fall activities: frames with the per-frame label `fall`, from the start of the lying phase, become `fall`.
  - Sitting and kneeling activities: frames in the second half of the activity become `sit`.
  - Walking, hopping and picking-up activities become `normal`.
  - A frame is used only when it has exactly one person box.
  - Subjects 9–10 form `val`.
  - The folder-to-class map is a table in the script. The script fails on an unmapped folder.
- **20 train clips** (from `split.csv`):
  - Frames inside `[fall_start_s + 0.5, fall_end_s − 0.5]` with exactly one person box become `fall`.
  - Non-fall frames are labelled by a new committed file `finetune/clip_postures.csv`
    (`clip_id, posture ∈ {sit, normal, skip}, note`). For example, children on the floor or in class are `sit`, and
    clips of deliberate lying on the floor are `skip`. Every crop of a frame gets that posture.
  - Claude fills in `clip_postures.csv` from each train clip's contact sheet and writes the reason in `note`. Claude
    also checks the crop review sheets (`--review`) before training. Both reviews are recorded in `REPORT_FINETUNE.md`.
  - Fall clips outside the interval are `normal`, unless the clip is listed as `skip`.
- **Balance:**
  - Sample frames ≥ 0.5 s apart.
  - At most 150 crops per clip or per CAUCAFall activity.
  - Write class counts to `stage2/stats.json`. The script fails if any class in `train` has < 300 crops.
- **Review sheets:** `--review` writes `results/sheets/crops_<class>.jpg` with 96 random crops per class, so labels
  can be checked by eye before training.

### Training on Kaggle: `finetune/kaggle_finetune.py bundle|push|status|pull --user <u>`

This reuses the helpers of `kaggle_bundle.py`: `kaggle()`, the upload workaround, private datasets and polling.

- **Dataset:** a private dataset `fallguard-finetune-v1` with `stage1/`, `stage2/`, the base weights `yolo11s.pt` and
  `jerryg best.pt` (sha256 checked before upload), the pinned Ultralytics 8.4.184 wheels and `train_stage{1,2}.py`.
- **Notebook `fallguard-ft-stage1`:**
  - `YOLO('yolo11s.pt').train(data=..., imgsz=704, epochs=60, batch=32, device=[0,1], save_period=5, time=5.5)`.
  - Defaults: `patience=15`, `seed=0`.
- **Notebook `fallguard-ft-stage2`:**
  - `YOLO('jerryg best.pt').train(data=stage2/, imgsz=128, epochs=40, batch=256, device=[0,1], time=5.5, seed=0)`.
  - The classifier head is rebuilt for 3 classes.
- **Outputs:** each notebook writes `best.pt`, `results.csv` and `args.yaml` into `ft_stage{1,2}.zip`.
- **Pull:** `pull` unpacks into `benchmark/weights/yolo11s-ft/best.pt` and `benchmark/weights/jerryg-ft3/best.pt`, then
  prints their sha256.

### Benchmark integration

- **`models.json`:**
  - `stage1` entry `yolo11s-ft`.
  - Candidate `jerryg-ft3` with `kind: classify`, `fall_labels: ["fall"]`, `imgsz: 128` and the notebook URL as `source_url`.
  - Their file entries carry `"local": true`: `fetch_models.py` never downloads them, but it still verifies the pinned sha256.
- **`run_benchmark.py`:**
  - New stage-1 variant `ft` = (`yolo11s-ft`, conf 0.3).
  - New flag `--split test|train|all` (default `all`). It filters the manifest by `split.csv` for scoring and for analysis.
  - With `--split test` or `--split all`, analysis outputs go to `results/split_test/` or `results/split_all/`. When
    `--split` is not given, outputs go to `results/` as in v3, so the v3 40-clip results stay untouched.
    Per-pipeline frames and events CSVs stay shared, because they are per clip.
- **Runs:** the new pairs are scored on all 40 clips; the 20 test clips are a subset of them.
- **Report:** a new `benchmark/REPORT_FINETUNE.md` (Vietnamese) with the same generated blocks, rendered from
  `results/split_test/`, plus a hand-written verdict for Goal 5.
  - A second set of blocks with a `_all40` suffix is rendered from `results/split_all/` (`--split all`, also a separate
    directory, so the v3 `results/` files stay untouched).
  - That section is headed as contaminated for the fine-tuned models.
- **Pairs:**
  - Scoring of the pairs s1 ∈ {pose, ft} × s2 ∈ {jerryg-v8x-cls, jerryg-ft3}.
  - Then `--latency-only` for those pairs, locally.

## Data and API changes

- **New committed files:** `benchmark/split.csv`, `benchmark/finetune/clip_postures.csv`, `benchmark/finetune/*.py`,
  `benchmark/REPORT_FINETUNE.md`.
- **`models.json`:** 1 stage-1 entry and 1 candidate. File entries gain an optional `local` field.
- **`run_benchmark.py`:** stage-1 variant `ft` and flag `--split`. The existing behaviour with `--split all` is unchanged.
- **No change** to app schemas, endpoints, env vars or `fallguard/`.

## Edge cases and errors

- **Annotation formats:** the E-FPDS or CAUCAFall format differs from what the converter expects → it stops before
  writing output and prints a sample file path.
- **Box rules:**
  - Fall frames with 0 or ≥ 2 person boxes are skipped. These are the frames where helpers kneel next to the person.
  - `square_crop` returns None when a box is < 16 px; the crop is skipped.
- **Leakage:** near-duplicates of benchmark frames are dropped, and their count is reported.
- **Split:** if no group assignment meets the split constraints, `make_split.py` exits 1. A test-clip id appearing in
  any training manifest makes the build fail.
- **Kaggle:**
  - The session hits the time limit → `time=5.5` stops training cleanly, and `save_period` keeps checkpoints.
  - DDP fails → the notebook retries with `device=0` and logs that it did.
- **Model checks:**
  - The classify fine-tune with a new class count must load in the benchmark adapter with `fall` in `model.names`.
    A missing class fails at load (the existing `label_ids` check).
  - The fine-tuned weights are unpinned or mismatched → the benchmark refuses to load them (existing `verify_file`).
- **Licenses:**
  - `jerryg-ft3` derives from unlicensed weights.
  - E-FPDS states no license.
  - Neither is committed. The report records both.

## Test plan

Offline unit tests in `tests/test_benchmark_finetune.py`:

- `test_split_is_grouped_stratified_and_deterministic`: same seed gives the same split; no group is on both sides;
  test has ≥ 8 event fall clips and the `long` clip.
- `test_split_test_clips_never_in_training_manifests`: the crop builders reject a `test` clip id.
- `test_clip_crop_labels_from_interval_and_postures`: synthetic frames inside and outside the fall interval, with one
  and with two boxes, map to fall, normal, sit or skip as specified.
- `test_caucafall_folder_map_rejects_unknown_folder`.
- `test_teacher_merge_adds_only_non_overlapping_boxes`: IoU ≥ 0.5 is not added, IoU < 0.5 is added, conf < 0.5 is ignored.
- `test_dhash_filter_drops_near_duplicates`: an image and its slightly resized copy fall within the threshold.
- `test_class_floor_fails_on_small_class`.
- `test_run_benchmark_split_filters_manifest_and_output_dir`.
- `test_fetch_models_local_entry_is_verified_not_downloaded`.

End-to-end check:
- `make_split.py`, `prepare_stage1.py`, `build_stage2_crops.py --review` and `kaggle_finetune.py bundle` all exit 0.
- Both notebooks reach `COMPLETE`, and `pull` writes both weights.
- `run_benchmark.py --split test --stage1-variants pose,ft` scores the new pairs, `--latency-only` times them, and
  `--report-only --split test` regenerates `REPORT_FINETUNE.md` with no diff on a second run.

## Acceptance criteria

- [ ] `benchmark/split.csv` has 40 rows, 20 per side, with no group on both sides. Test has ≥ 8 event fall clips and
      `yt_long_class1`.
- [ ] `stage2/stats.json` shows ≥ 300 train crops for each of `fall`, `sit` and `normal`, and no crop comes from a `test` clip.
- [ ] Both Kaggle notebooks end `COMPLETE` within 6 h each. `benchmark/weights/yolo11s-ft/best.pt` and
      `benchmark/weights/jerryg-ft3/best.pt` exist, and their sha256 is pinned in `models.json`.
- [ ] `results/split_test/summary.csv` has rows for the baseline pipeline and for every
      s1 ∈ {pose, ft} × s2 ∈ {jerryg-v8x-cls, jerryg-ft3} × trk ∈ {prod, gap1, gap2}, all `ok`, each with `p95_ms_median`.
- [ ] `REPORT_FINETUNE.md` states whether Goal 5 is met. It gives the event score, false-alarm clips, paired CI and
      p95 of `jerryg-ft3|s1=ft|trk=gap1` against the baseline on the same 20 clips.
- [ ] `REPORT_FINETUNE.md` has a section with the `_all40` blocks from `results/split_all/`, headed as contaminated.
      `results/summary.csv` (v3) is unchanged, which is checked by its hash before and after.
- [ ] `finetune/clip_postures.csv` covers every non-fall and every fall train clip, with a `note` per row.
      `REPORT_FINETUNE.md` records Claude's review of the postures and of the crop sheets.
- [ ] `pytest -q tests/test_benchmark_finetune.py tests/test_benchmark_metrics.py` passes.
- [ ] `git status` shows no training data and no fine-tuned `.pt` file staged.
- [ ] `git diff --stat -- "Fall detection/fallguard"` is empty.

## Decisions (2026-10-25)

- **E-FPDS:** used for research only in this university course project. The user deletes the project after the course.
- **Small test split:** the report also gives 40-clip results, marked contaminated. Only the 20-clip test decides Goal 5.
- **Labels review:** Claude reviews `clip_postures.csv` and the crop sheets.

## Open questions

None.
