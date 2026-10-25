# Fall model benchmark v3: more stage-2 candidates from Kaggle and Hugging Face

Status: draft · Date: 2026-10-24 · Builds on: `docs/specs/2026-10-24-fall-model-benchmark-v2.md` (v2, implemented in `Fall detection/benchmark/`; its full run stopped after the `prod` stage-1 variant)

## Problem

The 6 v1 candidates are weak on real CCTV.
- Fall-clip recall is at most 0.43 and stage-2 AP is 0.17–0.24 on the 40-clip v2 set.
- The baseline `leeyunjai-11x` has a median p95 of about 1.4 s on crowded frames, so it is not eligible.

A search of Hugging Face and Kaggle found 4 more fall detectors that fit the existing `yolo-detect` adapter, so they can be tested without new code paths or dependencies.

Three of them are on Kaggle, which needs an API token to download. The v2 run also still lacks the `lowconf` and `pose` stage-1 variants.

## Goals

1. **Add 4 stage-2 candidates** to `models.json`, each pinned by sha256:

   | id | Source | Stated license |
   |--|--|--|
   | `bertnardo-v8n` | Kaggle `bertnardomariouskono/fall-detection-yolov8` (pyTorch / yolov8-nano-best-weights / v1, `safeguard_best.pt`) | Apache 2.0 |
   | `khoa05ai-v8m` | Kaggle `khoa05ai/yolov8m-falldetection-3classes-v1` (pyTorch / default / v1, `best.pt`) | CC0 |
   | `doquanganh-falldetect` | Kaggle `doquanganh0812/falldetect` (other / default / v1, `best.pt`) | Apache 2.0 |
   | `kamalchibrani-v8` | Hugging Face `kamalchibrani/yolov8_fall_detection_25` (`best.pt`) | OpenRAIL |

   `fall_labels` are set explicitly from the class names stored in each checkpoint. A checkpoint that has no fall class, or is not an Ultralytics detect/classify model, is kept with `status: missing` and a note saying why.

2. **Kaggle downloads in `fetch_models.py`.**
   - A file entry with `"auth": "kaggle"` is downloaded with `Authorization: Bearer $KAGGLE_API_TOKEN`.
   - The token is read from the environment only. It is never written to disk or logged, and it is not sent on a redirect (Kaggle redirects to Google Cloud Storage).
3. **Finish the run: 10 candidates × 3 stage-1 variants × 3 trackers = 90 pipelines.**
   - `run_benchmark.py --resume` skips (model, stage-1 variant) pairs that are already `ok` in `results/runs.csv` and have a frames CSV. Scoring is deterministic, so a resumed run gives the same per-frame results.
   - Latency is still timed for every candidate of a variant in the same interleaved rounds, including resumed ones, so all latency numbers of a variant come from one session.
4. **Fix duplicate rows in `paired.csv`.** The same pair currently appears twice, once in each order.
5. **Write `REPORT.md`** (Vietnamese) with the v2 blocks and the v2 and v3 analysis, ending with the stage-2 and pipeline recommendations.

## Non-goals

- Models that need a new adapter or dependency, such as TensorFlow/Keras, RF-DETR, a custom ViT `.pth` or sequence models (LSTM, ST-GCN, VideoMAE). A later spec can add them.
- Changing `fallguard/`, `requirements.txt` or the production model.
- Committing weights, videos, `results/` or any token.
- A legal review of licenses. The report records each stated license and notes that a fine-tune of Ultralytics weights is an AGPL-3.0 derivative whatever its uploader states.

## Design

All changes are in `Fall detection/benchmark/` and `Fall detection/tests/`.

- **`models.json`:** 4 new `candidates` entries with the existing fields (`kind`, `backend`, `files[{url, path, sha256}]`, `fall_labels`, `imgsz`, `license`, `trained_on`, `notes`).
  - Kaggle file URLs have the form `https://www.kaggle.com/api/v1/models/<owner>/<slug>/<framework>/<instance>/<version>/download/<file>` and carry `"auth": "kaggle"`.
  - `trained_on` is left empty, since none of these model pages name a dataset, and the report says so.
- **`fetch_models.py`:**
  - `download(url, dest, ..., auth=None)` gains an `auth` parameter. For `'kaggle'` it adds the header through `Request.add_unredirected_header`, so urllib does not copy it to the redirect target.
  - `kaggle_token()` raises `RuntimeError('set KAGGLE_API_TOKEN ...')` when the variable is missing or empty.
  - The rest of the flow (https only, 2 GiB cap, `.part` file, `--pin`) does not change.
- **`run_benchmark.py`:**
  - `--resume`: before scoring a candidate under a variant, skip it when `runs.csv` has `status=ok` for (model, variant) and `frames_<model>@<variant>.csv` exists. A skipped candidate keeps its row and still joins that variant's latency rounds.
  - `paired_rows`: a pair is computed once per scope, whatever its order. `pair_row` already flips the sign when the stored order is reversed.
- **`REPORT.md`:** add the v2 generated markers (`results_ci`, `paired`, `subsets`, `stage2_only`, `pipelines`, `latency`) and update the hand-written sections.

## Data and API changes

- `models.json` has 4 new candidate entries, and file entries gain an optional `auth` field.
- New environment variable for `fetch_models.py` only: `KAGGLE_API_TOKEN`.
- New `run_benchmark.py` flag: `--resume`.
- App schemas, endpoints and `fallguard/` do not change.

## Edge cases and errors

- **Token:**
  - `KAGGLE_API_TOKEN` is missing → each Kaggle file fails with `[FAIL] ... set KAGGLE_API_TOKEN`, the other files still download, and the exit code is 1.
  - A wrong or expired token → HTTP 401/403 is reported for that file only.
- **Redirect:** a redirect to a non-https URL is refused, as in v1. The `Authorization` header is never sent to the redirect host.
- **Checkpoint:**
  - A checkpoint that fails `ULTRALYTICS_SAFE_LOAD` gets `status=failed` with the error, as in v2.
  - A checkpoint whose classes have no fall label is not run; see Goal 1.
- **`--resume`:**
  - A frames CSV without an `ok` runs row, or the reverse, is re-scored.
  - A changed manifest makes resumed rows stale, so `--resume` is only for continuing the same clip set. The README says so.
- **Kaggle rate limits or outages:** the download fails for that file only; rerunning `fetch_models.py` retries.

## Test plan

New tests in `tests/test_benchmark_metrics.py` (offline):

- `test_kaggle_auth_header_is_not_redirected`: a `Request` built by the download helper carries `Authorization` as an unredirected header, and `_HttpsOnlyRedirect.redirect_request` returns a request without it.
- `test_kaggle_token_missing_raises`: with no `KAGGLE_API_TOKEN`, `kaggle_token()` raises and the message names the variable.
- `test_paired_rows_compute_each_pair_once`: two rows that each rank first in one scope produce one row per (scope, unordered pair, metric).
- `test_resume_skips_only_complete_pairs`: the skip helper returns True only when the runs row is `ok` and the frames file exists.

End-to-end check:
- `KAGGLE_API_TOKEN=... .venv/Scripts/python -I benchmark/fetch_models.py --only <4 ids> --pin` pins 4 hashes.
- `.venv/Scripts/python -I benchmark/run_benchmark.py --stage1-variants prod,lowconf,pose --latency-runs 5 --resume` exits 0.
- `--report-only` then regenerates with no diff.

## Acceptance criteria

- [ ] `models.json` has 10 candidates. Each of the 4 new ones has a 64-hex `sha256`, explicit `fall_labels` (or `status: missing` with a reason), `license` and `source_url`.
- [ ] `fetch_models.py` exits 0 with `KAGGLE_API_TOKEN` set. Without it, the output contains `KAGGLE_API_TOKEN`, the exit code is 1, and the Hugging Face files still download.
- [ ] No Kaggle token value is in the repo: `git grep -nE "KGAT_[0-9a-f]{8}"` finds nothing, and neither does the same pattern over the untracked `Fall detection/benchmark/` and `docs/` files.
- [ ] `pytest -q tests/test_benchmark_metrics.py` passes with the 4 new tests, and `pytest -q` passes overall.
- [ ] `results/summary.csv` has 90 rows, one per pipeline. A `missing` candidate counts as 9 rows with that status.
- [ ] `results/latency.csv` has 5 runs per (stage-1 variant, ok model).
- [ ] `paired.csv` has no pair that appears in both orders within a scope.
- [ ] `REPORT.md` contains all v2 generated blocks and a stage-2 recommendation and a pipeline recommendation under rule v2, with numbers cited.
- [ ] `git diff --stat -- "Fall detection/fallguard" "Fall detection/requirements.txt"` is empty.

## Open questions

- Should the runner-up of a near-tie also be timed on a second machine before adoption? This is out of scope here; it is noted in the report.
