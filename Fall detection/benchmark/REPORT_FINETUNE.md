# Báo cáo fine-tune pipeline phát hiện ngã (v4)

Spec: `docs/specs/2026-10-25-fall-model-finetune.md`. Tiếp nối báo cáo v3 (`benchmark/REPORT.md`).

Các bảng giữa `<!-- BEGIN GENERATED -->` và `<!-- END GENERATED -->` do `run_benchmark.py --split test` (khối không hậu tố)
và `--split all` (khối `_all40`) sinh từ `results/split_test/` và `results/split_all/`; chạy lại `--report-only` sẽ sinh
lại y hệt. Phần còn lại viết tay.

## 1. Tóm tắt

**Goal 5 đạt theo đúng chữ của spec, nhưng không có bằng chứng cải thiện.** Trên 20 clip test,
`jerryg-ft3|s1=ft|trk=gap1` có điểm sự kiện 1 (5/11 clip ngã có cảnh báo, 4 clip cảnh báo sai), bằng baseline
`jerryg-v8x-cls|s1=pose|trk=gap1` (6/11, 5 clip cảnh báo sai). p95 trung vị là 53,6 ms so với 61,0 ms. Hiệu cặp bằng 0, CI 95%
[-7, 8]: **hoà**. Cả ba điều kiện của Goal 5 (≥, ≤, ≤ 200 ms) đều thoả, nhưng chủ yếu nhờ hoà ở điều kiện đầu.

Đọc kỹ thì cả hai bước fine-tune đều đi sai hướng so với mục tiêu ở REPORT.md §11:

- **Stage 1 `yolo11s-ft` thấy ít người hơn, không phải thấy người nằm tốt hơn.** Tỉ lệ frame ngã có ít nhất một người giảm
  từ 0,80 (`pose`) xuống 0,40. Số người trung bình mỗi frame bình thường giảm từ 5,4 xuống 1,4. Model tốt hơn ở 2 clip
  (`yt_doorbell_porch` 0,22 → 1,00, `yt_street_faint` 0,03 → 0,35) nhưng gần như mất hẳn người nhỏ hoặc ở xa trong CCTV thật
  (`yt_blind_yard` 0,67 → 0,02, `yt_shop_convulse` 1,00 → 0,04, `yt_cardiac_street` 1,00 → 0,31). E-FPDS quay từ độ cao robot,
  người to và gần camera, nên fine-tune làm model quên phần người nhỏ mà COCO đã dạy. Số clip cảnh báo sai giảm phần lớn vì
  model thấy ít người hơn: trẻ em trong lớp học không còn được phát hiện.
- **Stage 2 `jerryg-ft3` cảnh báo sai nhiều hơn** khi đi với stage 1 gốc: 8/9 clip không ngã của tập test so với 5/9.
  Trẻ em ngồi sàn và lớp học vẫn bị báo ngã (`yt_neg_kids_floor1`, `yt_neg_kids_floor3`, `yt_long_class1`). Lớp `sit` của
  CAUCAFall là người lớn ngồi ghế hoặc quỳ, nên model không tổng quát hoá sang trẻ ngồi sàn. Ngoài ra có thêm cảnh báo sai mới
  ở các clip ngồi hoặc nằm trên sàn, trên giường (`gmd_s2_adl09`, `gmd_s4_adl10`, `gmd_s4_adl11`, `yt_neg_ir_floor`).
- Tập test chỉ có 11 clip ngã tính sự kiện, nên mọi CI đều rộng; không cặp nào khác biệt có ý nghĩa.

**Khuyến nghị:** không thay pipeline v3. Muốn cải thiện thật cần dữ liệu stage 1 có người nhỏ, nhìn từ camera treo cao, và
dữ liệu `sit` có trẻ em ngồi sàn. Cả hai đều ngoài phạm vi spec này (non-goal: dataset khác, gán box tay).

## 2. Dữ liệu

### 2.1 Chia tập 20/20 (`benchmark/split.csv`)

`finetune/make_split.py` chia 40 clip thành 20 `train` / 20 `test`, seed 0. Các clip chung người hoặc chung cảnh nằm cùng
một phía: GMDCSA-24 theo subject, URFD là một nhóm, ba clip trẻ em ngồi sàn và `yt_long_class1` (cùng một trường) là một
nhóm, mỗi clip YouTube còn lại là một nhóm riêng. Trong 1000 cách gán ngẫu nhiên, chỉ giữ cách có đúng 20 clip test, ≥ 8
clip ngã tính sự kiện ở test và `yt_long_class1` ở test. Cách được chọn là cách gần một nửa nhất ở mỗi ô
(ngã / không ngã) × (real / lab).

| Phía | Clip | Clip ngã tính sự kiện | ngã / lab | ngã / real | không ngã / lab | không ngã / real |
|--|--|--|--|--|--|--|
| train | 20 | 10 | 6 | 7 | 5 | 2 |
| test | 20 | 11 | 3 | 8 | 4 | 5 |

Hệ quả: cả bốn clip của trường học (trẻ em ngồi sàn, lớp học dài) đều ở `test`, nên stage 2 không được học từ cảnh lớp
học. Đây là phép thử tổng quát hoá khó nhất cho lỗi "ngồi bị chấm là ngã" của v3.

### 2.2 Stage 1: E-FPDS

Giữ split gốc của E-FPDS: `train` → train, `valid` → val. Không dùng tập `test` của E-FPDS. Mỗi dòng nhãn là
`<1|-1> left right top bottom` (pixel); `1` là người ngã, `-1` là người không ngã, cả hai đều thành lớp `person`.

| | Số lượng |
|--|--|
| Ảnh train / val | 4.807 / 1.175 |
| Box E-FPDS | 6.051 |
| Box teacher thêm vào (`yolo11s`, conf ≥ 0,5) | 93 |
| Ảnh bị loại do gần trùng frame clip (dHash ≤ 6) | 1 (`train/split1/split1_128.png`) |
| Box quá nhỏ bị bỏ | 0 |

- **Lệch khỏi spec, luật teacher merge:** luật IoU < 0,5 để lọt các box teacher chỉ là **mảnh** của một người đã có nhãn
  (YOLO tách người nằm thành phần chân và phần thân). Đã thêm điều kiện bỏ box teacher nếu ≥ 50% diện tích nằm trong một box
  E-FPDS, nên số box teacher giảm từ 192 xuống 93.
- Xem mẫu 9 ảnh có box teacher: phần lớn là người thật bị E-FPDS bỏ sót (người ở mép khung, người ở cuối hành lang). Khoảng
  2/9 là nhận nhầm (quần áo treo trên giá). Không lọc thêm vì số này rất nhỏ so với 6.051 box gốc.
- Kiểm tra bằng mắt: box sau chuyển đổi ôm khít người.

### 2.3 Stage 2: CAUCAFall và 20 clip train

CAUCAFall (10 subject × 10 hoạt động, 20.001 frame) được tải về máy từ bản mirror Kaggle `tuyenldvn/caucafall` và kiểm tra
CRC. `classes.txt` ghi `nofall` / `fall`, nên id 1 là ngã. Có 6 ảnh không có file nhãn (ví dụ `cas200091 - copia.png`); các ảnh
này được bỏ qua và ghi log. Crop được cắt quanh box `yolo11s-pose` (conf 0,3), frame cách nhau ≥ 0,5 s.

| Nguồn | train fall | train sit | train normal | val fall | val sit | val normal |
|--|--|--|--|--|--|--|
| CAUCAFall (subject 1–8 train, 9–10 val) | 459 | 170 | 467 | 152 | 49 | 145 |
| 20 clip train (11 clip có crop) | 79 | 12 | 107 | – | – | – |
| **Tổng** | **538** | **182** | **574** | **152** | **49** | **145** |

- **Lệch khỏi spec, ngưỡng `sit`:** spec yêu cầu ≥ 300 crop mỗi lớp. `sit` chỉ có 182, vì CAUCAFall chỉ có Sit down và Kneel
  (lấy nửa sau mỗi hoạt động) và 20 clip train gần như không có cảnh ngồi rõ ràng. Người dùng chọn hạ ngưỡng riêng của `sit`
  xuống 150 thay vì lấy thêm các frame gần trùng nhau (`finetune/common.py: CLASS_FLOOR_OVERRIDES`).
- Không crop nào đến từ clip `test`: build kiểm tra nguồn gốc mọi crop với `split.csv`.

### 2.4 Review nhãn tư thế (`finetune/clip_postures.csv`)

Claude xem contact sheet (1 frame/giây, vùng ngã tô đỏ) của cả 20 clip train và gán một tư thế cho các frame ngoài khoảng
ngã. Mọi crop của frame đó đều nhận nhãn này, nên clip lẫn nhiều tư thế, hoặc clip có người nằm ngoài khoảng ngã, được
gán `skip`.

- `normal` (7): gmd_s3_fall05, gmd_s3_fall07, urfd_fall01_cam1, yt_drunk_work, yt_neg_living_dance, yt_pizza_elder,
  yt_school_aed. Người đứng hoặc đi trước khi ngã, hoặc không có frame nào sau khoảng ngã.
- `sit` (3): gmd_s3_fall18 (ngồi mép giường trước khi đứng dậy rồi ngã), urfd_fall10_cam1 và urfd_fall20_cam1 (nhìn từ
  trên xuống, ngồi ghế ở 0 s).
- `skip` (10): yt_carehome_chair, gmd_s1_adl01, gmd_s1_adl15, gmd_s3_adl06, urfd_adl30_cam0, yt_karate_hall,
  yt_hospital_floor, yt_neg_crew_floor, yt_restaurant_cpr, gmd_s3_adl09. Lý do có thể là nằm trên giường hoặc trên sàn, nửa
  ngồi nửa đứng, người ngã vẫn nằm sau `fall_end_s`, hoặc cảnh đông lẫn ngồi, đứng và nằm.
- Hai nhãn đã sửa so với lượt đầu: `yt_restaurant_cpr` đổi `sit` → `skip`, vì ở 2–3 s người đàn ông đã trượt khỏi ghế
  (3/7 frame); `urfd_fall10_cam1` đổi `skip` → `sit`, vì ở 0 s người đang ngồi trên chiếc ghế thấy rõ ở các frame sau.

Hệ quả: clip train cho rất ít crop `sit`. Lớp `sit` dựa chủ yếu vào CAUCAFall (Sit down, Kneel).

**Lệch khỏi spec:** spec ghi "frame ngoài khoảng ngã của clip ngã là `normal`, trừ khi clip là `skip`". Ở đây các frame đó
nhận tư thế của clip trong `clip_postures.csv`, vì 3 clip ngã (`gmd_s3_fall18`, `urfd_fall10_cam1`, `urfd_fall20_cam1`) có
người **ngồi** trước khi ngã; gán `normal` sẽ dạy model rằng tư thế ngồi thuộc lớp `normal`. Đây là 12 crop `sit` từ clip ở mục 2.3.

### 2.5 Review sheet crop (`results/sheets/crops_<lớp>.jpg`)

Claude xem cả ba sheet (96 crop ngẫu nhiên mỗi lớp) và riêng toàn bộ 101 crop `fall` lấy từ clip.

- `sit`: người quỳ hoặc ngồi ghế; một ít frame đang ngồi xuống hoặc đứng dậy. Chấp nhận được.
- `normal`: đi, nhảy, cúi nhặt đồ. Đúng.
- `fall` từ CAUCAFall và phần lớn clip: người nằm trên sàn, hoặc chống tay quỳ ngay sau cú ngã (`yt_pizza_elder`). Đúng.
- **Lỗi đã sửa:** `yt_restaurant_cpr` (13 crop) và `yt_school_aed` (khoảng 13 crop) cho crop `fall` là **người cứu đang đứng
  hoặc quỳ**, không phải nạn nhân. Stage 1 không thấy người nằm, nên "đúng 1 box" lại là box của người khác. **Lệch khỏi
  spec:** thêm cột `fall_crops` (`keep` / `skip`) vào `clip_postures.csv`; hai clip này là `skip`, nên số crop `fall` giảm từ
  560 xuống 538.

## 3. Huấn luyện trên Kaggle

Cả hai notebook chạy trên Kaggle 2× Tesla T4, bằng DDP (`device=[0,1]`), không cần fallback. Dataset riêng tư
`fallguard-finetune-v1`, không bật internet.

| | Stage 1 `yolo11s-ft` | Stage 2 `jerryg-ft3` |
|--|--|--|
| Tham số | imgsz 704, batch 32, `epochs=60`, `time=5.5`, patience 15, seed 0 | imgsz 128, batch 256, `epochs=40`, `time=5.5`, seed 0 |
| Kết thúc | dừng sớm ở epoch 38, 0,74 giờ | dừng sớm ở epoch 144, 0,18 giờ |
| Epoch tốt nhất (theo val) | 23: mAP50 0,874, mAP50-95 0,432 (E-FPDS val) | 44: top1 0,971 (CAUCAFall subject 9–10) |
| sha256 `best.pt` | `f3801090569bfcc53c88cf3f2d80de9089603872270c3a0dfe984e08c1f7e464` | `3954f965bd737106f3eeb5845200c9ac61a510dbf46d456f692f5e4f0c71665f` |

- Với Ultralytics, `time` ghi đè `epochs`: số epoch được tính lại cho vừa 5,5 giờ, nên stage 2 chạy 144 epoch và dừng theo
  patience mặc định 100. Epoch tốt nhất chọn theo tập val của từng dataset, không bao giờ theo clip test.
- Các lần chạy lỗi trước đó (đã sửa trong `kaggle_finetune.py`): notebook mount phiên bản dataset cũ (`datasets status` báo
  ready trước khi phiên bản mới xử lý xong; nay chờ file đánh dấu bundle); thư mục làm việc chỉ đọc (Ultralytics tạo `./weights`;
  nay chạy với cwd `/kaggle/working`). Notebook prep cắt crop CAUCAFall trên Kaggle chạy hơn 4 giờ không ra kết quả và đã bị
  huỷ; crop được cắt trên máy thay vào đó.
- Độ trễ của các cặp trong báo cáo này (kể cả baseline, đo lại cùng phiên trên RTX 3060 Laptop) nằm ở
  `results/latency_split.csv`. Lần đo lại đầu tiên đã ghi đè 5 dòng của cặp `jerryg-v8x-cls|s1=pose` trong `results/latency.csv`
  của v3 trước khi hai file được tách; giá trị gốc (p95 trung vị 73,4 ms) chỉ còn trong REPORT.md đã commit.

## 4. Tập test (20 clip)

<!-- BEGIN GENERATED: clips -->
| clip_id | Nguồn | Góc nhìn | Ánh sáng | Loại | Ngã (s) | Ghi chú | File |
|--|--|--|--|--|--|--|--|
| yt_atm_collapse | youtube | ceiling | day | ngã | 0.8–11.0 | real CCTV; man collapses at an ATM; zoomed replay then cut to the wide shot at ~2.5 s; two helpers cross the frame ~5-10 s; trimmed to skip a first replay and the interview; times checked on 0.5 s frames | có |
| yt_doorbell_porch | youtube | wall | day | ngã | 10.0–17.7 | real doorbell camera; man leans on the railing then sinks to his knees and lies prone from ~11.5 s; trimmed before the interview; times checked on 0.5 s frames | có |
| yt_office_staged | youtube | ceiling | day | ngã | 7.5–19.2 | real office surveillance; staged fraud fall (lowers himself) at ~7.5-8.5 s then lies; caption overlays; times checked on 0.5 s frames | có |
| gmd_s2_fall04 | GMDCSA-24 | wall | day | ngã | 3.3–10.0 | backward fall after looking out of a window; annotated | có |
| gmd_s2_fall10 | GMDCSA-24 | wall | night | ngã | 2.0–11.0 | night; side fall then rolls onto the back; annotated | có |
| gmd_s2_fall19 | GMDCSA-24 | wall | day | ngã | 8.2–15.0 | eating while standing then forward fall; annotated | có |
| gmd_s4_adl10 | GMDCSA-24 | wall | day | không ngã | — | hard negative: walks then lies down on the bed | có |
| gmd_s2_adl09 | GMDCSA-24 | wall | day | không ngã | — | hard negative: gets up from the bed then sits on the floor | có |
| gmd_s2_adl22 | GMDCSA-24 | wall | night | không ngã | — | hard negative: night; push-ups then sits | có |
| yt_cardiac_street | youtube | ceiling | day | ngã | 11.5–42.5 | real outdoor CCTV, far camera so the person is small; man walks then collapses ~11.5-12.5 s and lies; helpers arrive ~15 s and kneel around him from ~24 s; trimmed before a zoomed cut; times checked on 0.5 s frames | có |
| yt_ring_heat | youtube | wall | day | ngã | 2.0–36.5 | real Ring doorbell (fisheye); man collapses ~2-3.5 s and lies along the bottom edge, mostly out of frame; caption overlays; neighbour arrives ~34 s; times checked on 0.5 s frames | có |
| yt_blind_yard | youtube | wall | day | ngã | 1.5–21.5 | real home-yard IP camera; blind elderly woman falls ~1.5-2 s (normal-speed footage after the uploader preview); cut to a second yard camera at ~5 s where she lies; captions; times checked on 0.5 s frames | có |
| yt_neg_ir_floor | youtube | ceiling | ir | không ngã | — | hard negative: real nursery IR camera; parent lies on the floor by the cot then crawls out of the room; trimmed before a text overlay | có |
| yt_neg_kids_floor1 | youtube | ceiling | day | không ngã | — | hard negative: real classroom CCTV; children sit on the floor in a circle | có |
| yt_neg_kids_floor2 | youtube | ceiling | day | không ngã | — | hard negative: real classroom CCTV; children sit on the floor | có |
| yt_neg_kids_floor3 | youtube | ceiling | day | không ngã | — | hard negative: real classroom CCTV; children on the floor and on low chairs | có |
| yt_long_class1 | youtube | ceiling | day | không ngã | — | long; real-time classroom CCTV (burned-in clock checked); children sit at tables, adults walk and bend | có |
| yt_shop_convulse | youtube | ceiling | day | ngã | 9.0–45.0 | uncertain; real convenience-store CCTV (high angle); man at the left edge sinks to the floor slowly ~9-16 s and convulses there; often half out of frame; burned-in subtitles; times checked on 0.5 s frames | có |
| yt_street_faint | youtube | ceiling | day | ngã | 7.0–18.0 | uncertain; real street CCTV, man is tiny in frame; sinks to sitting ~7-8 s then lies on the pavement from ~12 s; red circle overlay 0-13 s; times checked on 0.5 s frames | có |
| gmd_s4_adl11 | GMDCSA-24 | wall | day | không ngã | — | hard negative: sits on the floor copying from a book | có |
<!-- END GENERATED: clips -->

## 5. Ứng viên

<!-- BEGIN GENERATED: candidates -->
| id | Loại | Nguồn | License | trained_on | Leakage | Trạng thái |
|--|--|--|--|--|--|--|
| leeyunjai-11x | yolo-detect | https://huggingface.co/leeyunjai/yolo11-falldetect | not stated |  | không | ok |
| syed-le2i-11n | yolo-detect | https://github.com/SyedBurhanAhmed/Real-Time-Fall-Detection-using-YOLO | MIT (data CC BY 4.0) | Le2i, Roboflow le2iahlam/le2i-ahlam | không | ok |
| valentin-ca3o8-v8n | yolo-detect | https://github.com/ValentinOzeel/Fall_Dectection_App | no LICENSE file (data CC BY 4.0) | Roboflow fall-detection-ca3o8, Roboflow wuyujie/fall-7lbue | không | ok |
| melih-3cls-11n | yolo-detect | https://huggingface.co/melihuzunoglu/human-fall-detection | AGPL-3.0 | Roboflow (custom, unnamed) | không | ok |
| jerryg-v8x-cls | classify | https://huggingface.co/JerryG-TAMU/YOLO_falldown | not stated | own set (458 train / 106 test images, TAMU/UTSA) | không | ok |
| pose-rule-yolo11s | pose | https://github.com/ultralytics/assets/releases/tag/v8.3.0 | AGPL-3.0 | COCO-Pose | không | ok |
| bertnardo-v8n | yolo-detect | https://www.kaggle.com/models/bertnardomariouskono/fall-detection-yolov8 | Apache 2.0 (as stated on Kaggle) |  | không | ok |
| khoa05ai-v8m | yolo-detect | https://www.kaggle.com/models/khoa05ai/yolov8m-falldetection-3classes-v1 | CC0 (as stated on Kaggle) |  | không | ok |
| doquanganh-falldetect | yolo-detect | https://www.kaggle.com/models/doquanganh0812/falldetect | Apache 2.0 (as stated on Kaggle) |  | không | ok |
| kamalchibrani-v8 | yolo-detect | https://huggingface.co/kamalchibrani/yolov8_fall_detection_25 | OpenRAIL (as stated on Hugging Face) |  | không | ok |
| jerryg-ft3 | classify | https://www.kaggle.com/code/triuinhhi/fallguard-ft-stage2 | not stated (derived from jerryg-v8x-cls, unlicensed) | CAUCAFall, benchmark split.csv train clips | không | ok |
<!-- END GENERATED: candidates -->

## 6. Goal 5: `jerryg-ft3|s1=ft|trk=gap1` so với baseline trên 20 clip test

Điều kiện đạt: điểm sự kiện ≥ baseline, số clip cảnh báo sai ≤ baseline, p95 trung vị ≤ 200 ms trên RTX 3060 Laptop.
Baseline là `jerryg-v8x-cls|s1=pose|trk=gap1`, pipeline v3 đề xuất, phân tích lại trên cùng 20 clip.

<!-- BEGIN GENERATED: goal -->
| Pipeline | Điểm sự kiện [CI 95%] | Clip ngã cảnh báo | Clip cảnh báo sai | Cảnh báo sai/giờ | F1 frame | p95 trung vị (ms) |
|--|--|--|--|--|--|--|
| jerryg-ft3\|s1=ft\|trk=gap1 | 1 [-3, 5] | 5/11 | 4 | 107.89 | 0.1735 | 53.6 |
| jerryg-v8x-cls\|s1=pose\|trk=gap1 | 1 [-4, 6] | 6/11 | 5 | 815.18 | 0.2468 | 61.0 |

Hiệu cặp `jerryg-ft3|s1=ft|trk=gap1` − `jerryg-v8x-cls|s1=pose|trk=gap1` = 0 điểm sự kiện, CI 95% [-7, 8] → hoà (tie).

- ✅ điểm sự kiện 1 ≥ 1 (baseline)
- ✅ clip cảnh báo sai 4 ≤ 5 (baseline)
- ✅ p95 trung vị 53.6 ms ≤ 200 ms

**Goal 5: ĐẠT** (tính tự động từ ba điều kiện trên).
<!-- END GENERATED: goal -->

## 7. Mọi tổ hợp và độ trễ

<!-- BEGIN GENERATED: pipelines -->
| Hạng | Pipeline | Điểm sự kiện [CI 95%] | Clip ngã cảnh báo | Clip cảnh báo sai | Cảnh báo sai/giờ | F1 frame | Stage-1 recall | p95 trung vị (ms) | ≤ 200 ms |
|--|--|--|--|--|--|--|--|--|--|
| 1 | bertnardo-v8n\|s1=pose\|trk=gap1 | 3 [0, 6] | 3/11 | 0 | 0.00 | 0.3234 | 0.803 |  | không |
| 2 | bertnardo-v8n\|s1=pose\|trk=gap2 | 3 [0, 6] | 3/11 | 0 | 0.00 | 0.3234 | 0.803 |  | không |
| 3 | bertnardo-v8n\|s1=pose\|trk=prod | 3 [0, 6] | 3/11 | 0 | 0.00 | 0.3234 | 0.803 |  | không |
| 4 | kamalchibrani-v8\|s1=pose\|trk=gap1 | 3 [-1, 7] | 8/11 | 5 | 803.20 | 0.2863 | 0.803 |  | không |
| 5 | kamalchibrani-v8\|s1=pose\|trk=gap2 | 3 [-1, 7] | 8/11 | 5 | 839.16 | 0.2863 | 0.803 |  | không |
| 6 | bertnardo-v8n\|s1=lowconf\|trk=gap1 | 3 [0, 6] | 3/11 | 0 | 0.00 | 0.2413 | 0.818 |  | không |
| 7 | bertnardo-v8n\|s1=lowconf\|trk=gap2 | 3 [0, 6] | 3/11 | 0 | 0.00 | 0.2413 | 0.818 |  | không |
| 8 | bertnardo-v8n\|s1=lowconf\|trk=prod | 3 [0, 6] | 3/11 | 0 | 0.00 | 0.2413 | 0.818 |  | không |
| 9 | bertnardo-v8n\|s1=prod\|trk=gap1 | 3 [0, 6] | 3/11 | 0 | 0.00 | 0.2327 | 0.735 |  | không |
| 10 | bertnardo-v8n\|s1=prod\|trk=gap2 | 3 [0, 6] | 3/11 | 0 | 0.00 | 0.2327 | 0.735 |  | không |
<!-- END GENERATED: pipelines -->

<!-- BEGIN GENERATED: latency -->
| Stage 1 | Stage 2 | Số lần chạy | p95 từng lần (ms) | p95 trung vị (ms) | TB (ms) |
|--|--|--|--|--|--|
| pose | jerryg-ft3 | 5 | 62.5 / 56.7 / 61.7 / 54.6 / 64.7 | 61.7 | 31.6 |
| pose | jerryg-v8x-cls | 5 | 59.9 / 61.0 / 64.5 / 64.1 / 57.4 | 61.0 | 32.0 |
| ft | jerryg-ft3 | 5 | 52.3 / 55.7 / 53.6 / 55.3 / 52.3 | 53.6 | 27.6 |
| ft | jerryg-v8x-cls | 5 | 55.2 / 53.3 / 58.2 / 55.8 / 52.6 | 55.2 | 27.3 |

Mẫu cố định 200 frame có người (seed 0, lần lượt qua từng clip), stage 1 + crop + stage 2, CUDA synchronize trước và sau mỗi frame. Mỗi vòng đo lần lượt mọi model nên nhiệt độ GPU ảnh hưởng đều. Số người mỗi frame trong mẫu (stage 1 đầu tiên): trung vị 1, 38/200 frame có ≥ 6 người; stage 2 chạy theo batch 2 crop nên thời gian tăng gần tuyến tính theo số người.
<!-- END GENERATED: latency -->

## 8. So sánh cặp và đề xuất

<!-- BEGIN GENERATED: paired -->
| Phạm vi | A | B | Chỉ số | A − B | CI 95% | Kết luận |
|--|--|--|--|--|--|--|
| pipeline tốt nhất | jerryg-v8x-cls\|s1=ft\|trk=prod | jerryg-ft3\|s1=ft\|trk=prod | điểm sự kiện | 1 | [-3, 5] | hoà (tie) |
| pipeline tốt nhất | jerryg-v8x-cls\|s1=ft\|trk=prod | jerryg-ft3\|s1=ft\|trk=prod | F1 frame | 0.0370 | [-0.0241, 0.0887] | hoà (tie) |
| pipeline tốt nhất | jerryg-v8x-cls\|s1=ft\|trk=prod | bertnardo-v8n\|s1=prod\|trk=prod | điểm sự kiện | 0 | [-6, 5] | hoà (tie) |
| pipeline tốt nhất | jerryg-v8x-cls\|s1=ft\|trk=prod | bertnardo-v8n\|s1=prod\|trk=prod | F1 frame | -0.0222 | [-0.2023, 0.1104] | hoà (tie) |
| pipeline tốt nhất | jerryg-v8x-cls\|s1=ft\|trk=prod | doquanganh-falldetect\|s1=prod\|trk=prod | điểm sự kiện | 2 | [-3, 6] | hoà (tie) |
| pipeline tốt nhất | jerryg-v8x-cls\|s1=ft\|trk=prod | doquanganh-falldetect\|s1=prod\|trk=prod | F1 frame | 0.0745 | [-0.0866, 0.2767] | hoà (tie) |
| pipeline tốt nhất | jerryg-v8x-cls\|s1=ft\|trk=prod | jerryg-v8x-cls\|s1=prod\|trk=prod | điểm sự kiện | 4 | [-3, 10] | hoà (tie) |
| pipeline tốt nhất | jerryg-v8x-cls\|s1=ft\|trk=prod | jerryg-v8x-cls\|s1=prod\|trk=prod | F1 frame | 0.0056 | [-0.2090, 0.1506] | hoà (tie) |
| pipeline tốt nhất | jerryg-v8x-cls\|s1=ft\|trk=prod | kamalchibrani-v8\|s1=prod\|trk=prod | điểm sự kiện | 4 | [-3, 10] | hoà (tie) |
| pipeline tốt nhất | jerryg-v8x-cls\|s1=ft\|trk=prod | kamalchibrani-v8\|s1=prod\|trk=prod | F1 frame | -0.0538 | [-0.3275, 0.1338] | hoà (tie) |
| pipeline tốt nhất | jerryg-v8x-cls\|s1=ft\|trk=prod | khoa05ai-v8m\|s1=prod\|trk=prod | điểm sự kiện | 5 | [-1, 11] | hoà (tie) |
| pipeline tốt nhất | jerryg-v8x-cls\|s1=ft\|trk=prod | khoa05ai-v8m\|s1=prod\|trk=prod | F1 frame | -0.0413 | [-0.2807, 0.1216] | hoà (tie) |
| pipeline tốt nhất | jerryg-v8x-cls\|s1=ft\|trk=prod | leeyunjai-11x\|s1=prod\|trk=prod | điểm sự kiện | 4 | [-2, 9] | hoà (tie) |
| pipeline tốt nhất | jerryg-v8x-cls\|s1=ft\|trk=prod | leeyunjai-11x\|s1=prod\|trk=prod | F1 frame | -0.0033 | [-0.2680, 0.1688] | hoà (tie) |
| pipeline tốt nhất | jerryg-v8x-cls\|s1=ft\|trk=prod | melih-3cls-11n\|s1=prod\|trk=prod | điểm sự kiện | 6 | [0, 11] | hoà (tie) |
| pipeline tốt nhất | jerryg-v8x-cls\|s1=ft\|trk=prod | melih-3cls-11n\|s1=prod\|trk=prod | F1 frame | 0.1685 | [0.0740, 0.3335] | khác biệt (different) |
| pipeline tốt nhất | jerryg-v8x-cls\|s1=ft\|trk=prod | pose-rule-yolo11s\|s1=prod\|trk=prod | điểm sự kiện | 4 | [-1, 9] | hoà (tie) |
| pipeline tốt nhất | jerryg-v8x-cls\|s1=ft\|trk=prod | pose-rule-yolo11s\|s1=prod\|trk=prod | F1 frame | 0.1029 | [-0.0555, 0.2370] | hoà (tie) |
| pipeline tốt nhất | jerryg-v8x-cls\|s1=ft\|trk=prod | syed-le2i-11n\|s1=prod\|trk=prod | điểm sự kiện | 6 | [0, 11] | hoà (tie) |
| pipeline tốt nhất | jerryg-v8x-cls\|s1=ft\|trk=prod | syed-le2i-11n\|s1=prod\|trk=prod | F1 frame | 0.0858 | [-0.1912, 0.3420] | hoà (tie) |
| pipeline tốt nhất | jerryg-v8x-cls\|s1=ft\|trk=prod | valentin-ca3o8-v8n\|s1=prod\|trk=prod | điểm sự kiện | 3 | [-3, 8] | hoà (tie) |
| pipeline tốt nhất | jerryg-v8x-cls\|s1=ft\|trk=prod | valentin-ca3o8-v8n\|s1=prod\|trk=prod | F1 frame | -0.0215 | [-0.3005, 0.1668] | hoà (tie) |
| Goal 5 | jerryg-ft3\|s1=ft\|trk=gap1 | jerryg-v8x-cls\|s1=pose\|trk=gap1 | điểm sự kiện | 0 | [-7, 8] | hoà (tie) |
| Goal 5 | jerryg-ft3\|s1=ft\|trk=gap1 | jerryg-v8x-cls\|s1=pose\|trk=gap1 | F1 frame | -0.0734 | [-0.2746, 0.0698] | hoà (tie) |
<!-- END GENERATED: paired -->

<!-- BEGIN GENERATED: recommendation -->
Luật v2: chỉ xét pipeline có trạng thái ok và p95 trung vị ≤ 200 ms; xếp theo điểm sự kiện (số clip ngã được cảnh báo − số clip cảnh báo sai) ở ngưỡng 0.4, rồi F1 frame, rồi p95 trung vị. Nếu CI 95% của hiệu điểm sự kiện giữa hai pipeline đầu chứa 0 thì coi là hoà và xét lần lượt: cảnh báo sai/giờ thấp hơn, có license, p95 trung vị thấp hơn.

**Đề xuất stage 2 cho pipeline hiện tại (s1=prod, trk=prod)**

_Không có pipeline nào có trạng thái ok và p95 trung vị ≤ 200 ms._

**Đề xuất pipeline đầy đủ (mọi tổ hợp)**

| Hạng | Pipeline | Điểm sự kiện [CI 95%] | Clip ngã cảnh báo | Clip cảnh báo sai | Cảnh báo sai/giờ | F1 frame | p95 trung vị (ms) | License |
|--|--|--|--|--|--|--|--|--|
| 1 | jerryg-v8x-cls\|s1=ft\|trk=prod | 3 [-2, 7] | 6/11 | 3 | 0.00 | 0.2105 | 55.2 | not stated |
| 2 | jerryg-ft3\|s1=ft\|trk=prod | 2 [-2, 6] | 5/11 | 3 | 83.92 | 0.1735 | 53.6 | not stated (derived from jerryg-v8x-cls, unlicensed) |
| 3 | jerryg-v8x-cls\|s1=pose\|trk=gap1 | 1 [-4, 6] | 6/11 | 5 | 815.18 | 0.2468 | 61.0 | not stated |
| 4 | jerryg-v8x-cls\|s1=pose\|trk=gap2 | 1 [-4, 6] | 6/11 | 5 | 875.12 | 0.2468 | 61.0 | not stated |
| 5 | jerryg-v8x-cls\|s1=ft\|trk=gap1 | 1 [-4, 6] | 6/11 | 5 | 0.00 | 0.2105 | 55.2 | not stated |
| 6 | jerryg-v8x-cls\|s1=ft\|trk=gap2 | 1 [-4, 6] | 6/11 | 5 | 0.00 | 0.2105 | 55.2 | not stated |
| 7 | jerryg-ft3\|s1=ft\|trk=gap1 | 1 [-3, 5] | 5/11 | 4 | 107.89 | 0.1735 | 53.6 | not stated (derived from jerryg-v8x-cls, unlicensed) |
| 8 | jerryg-ft3\|s1=ft\|trk=gap2 | 1 [-3, 5] | 5/11 | 4 | 155.84 | 0.1735 | 53.6 | not stated (derived from jerryg-v8x-cls, unlicensed) |
| 9 | jerryg-v8x-cls\|s1=pose\|trk=prod | -1 [-6, 4] | 4/11 | 5 | 755.24 | 0.2468 | 61.0 | not stated |
| 10 | jerryg-ft3\|s1=pose\|trk=gap1 | -3 [-7, 1] | 5/11 | 8 | 359.64 | 0.2142 | 61.7 | not stated (derived from jerryg-v8x-cls, unlicensed) |

Hai pipeline đầu: `jerryg-v8x-cls|s1=ft|trk=prod` − `jerryg-ft3|s1=ft|trk=prod` = 1 điểm sự kiện, CI 95% [-3, 5] → **hoà (tie)**. Áp dụng tie-break (cảnh báo sai/giờ thấp hơn, rồi có license, rồi p95 trung vị thấp hơn) → `jerryg-v8x-cls|s1=ft|trk=prod`.

**Đề xuất: `jerryg-v8x-cls|s1=ft|trk=prod`**: cảnh báo đúng 6/11 clip ngã (recall 0.55 [0.27, 0.82]), cảnh báo sai 3 clip (0.00/giờ, cơ sở: long), F1 frame 0.210 [0.109, 0.380], p95 trung vị 55.2 ms.

Chỉ xét nhóm `real` (youtube), cùng luật v2: đứng đầu là `jerryg-v8x-cls|s1=ft|trk=prod` (3 clip ngã cảnh báo, 3 clip cảnh báo sai) → không đổi người thắng.

So với pipeline production của cùng stage 2 (`jerryg-v8x-cls|s1=prod|trk=prod`): +4 điểm sự kiện, CI 95% [-3, 10] → hoà (tie).
<!-- END GENERATED: recommendation -->

## 9. Kết quả trên cả 40 clip: **bị nhiễm (contaminated)**

**Cảnh báo:** 20 trong 40 clip là dữ liệu huấn luyện stage 2 của `jerryg-ft3`. Với các pipeline dùng `jerryg-ft3`, số liệu
dưới đây bị thổi phồng và không được dùng để kết luận. Chỉ kết quả 20 clip test ở mục 6 quyết định Goal 5. Các pipeline
chỉ dùng model gốc (`jerryg-v8x-cls`) thì không bị ảnh hưởng. Stage 1 `yolo11s-ft` không học từ clip nào: ảnh E-FPDS gần
trùng với frame clip đã bị lọc.

<!-- BEGIN GENERATED: goal_all40 -->
| Pipeline | Điểm sự kiện [CI 95%] | Clip ngã cảnh báo | Clip cảnh báo sai | Cảnh báo sai/giờ | F1 frame | p95 trung vị (ms) |
|--|--|--|--|--|--|--|
| jerryg-ft3\|s1=ft\|trk=gap1 | 2 [-4, 8] | 9/21 | 7 | 107.89 | 0.2439 | 53.6 |
| jerryg-v8x-cls\|s1=pose\|trk=gap1 | 6 [0, 12] | 11/21 | 5 | 815.18 | 0.3488 | 61.0 |

Hiệu cặp `jerryg-ft3|s1=ft|trk=gap1` − `jerryg-v8x-cls|s1=pose|trk=gap1` = -4 điểm sự kiện, CI 95% [-12, 5] → hoà (tie).

- ❌ điểm sự kiện 2 ≥ 6 (baseline)
- ❌ clip cảnh báo sai 7 ≤ 5 (baseline)
- ✅ p95 trung vị 53.6 ms ≤ 200 ms

_Chỉ để tham khảo: tập clip này chứa dữ liệu huấn luyện stage 2 (bị nhiễm), nên không quyết định Goal 5. Chỉ kết quả trên 20 clip test quyết định._
<!-- END GENERATED: goal_all40 -->

<!-- BEGIN GENERATED: pipelines_all40 -->
| Hạng | Pipeline | Điểm sự kiện [CI 95%] | Clip ngã cảnh báo | Clip cảnh báo sai | Cảnh báo sai/giờ | F1 frame | Stage-1 recall | p95 trung vị (ms) | ≤ 200 ms |
|--|--|--|--|--|--|--|--|--|--|
| 1 | jerryg-v8x-cls\|s1=pose\|trk=gap1 | 6 [0, 12] | 11/21 | 5 | 815.18 | 0.3488 | 0.812 | 61.0 | có |
| 2 | jerryg-v8x-cls\|s1=pose\|trk=gap2 | 6 [0, 12] | 11/21 | 5 | 875.12 | 0.3488 | 0.812 | 61.0 | có |
| 3 | jerryg-v8x-cls\|s1=lowconf\|trk=gap1 | 6 [0, 12] | 11/21 | 5 | 1186.81 | 0.3277 | 0.816 |  | không |
| 4 | bertnardo-v8n\|s1=pose\|trk=gap1 | 5 [2, 9] | 5/21 | 0 | 0.00 | 0.3729 | 0.812 |  | không |
| 5 | bertnardo-v8n\|s1=pose\|trk=gap2 | 5 [2, 9] | 5/21 | 0 | 0.00 | 0.3729 | 0.812 |  | không |
| 6 | bertnardo-v8n\|s1=pose\|trk=prod | 5 [2, 9] | 5/21 | 0 | 0.00 | 0.3729 | 0.812 |  | không |
| 7 | kamalchibrani-v8\|s1=pose\|trk=gap1 | 5 [-1, 11] | 12/21 | 7 | 803.20 | 0.3591 | 0.812 |  | không |
| 8 | kamalchibrani-v8\|s1=pose\|trk=gap2 | 5 [-1, 11] | 12/21 | 7 | 839.16 | 0.3591 | 0.812 |  | không |
| 9 | leeyunjai-11x\|s1=pose\|trk=gap1 | 5 [-1, 11] | 13/21 | 8 | 671.33 | 0.3309 | 0.812 |  | không |
| 10 | leeyunjai-11x\|s1=pose\|trk=gap2 | 5 [-1, 11] | 13/21 | 8 | 743.26 | 0.3309 | 0.812 |  | không |
<!-- END GENERATED: pipelines_all40 -->

<!-- BEGIN GENERATED: paired_all40 -->
| Phạm vi | A | B | Chỉ số | A − B | CI 95% | Kết luận |
|--|--|--|--|--|--|--|
| pipeline tốt nhất | jerryg-v8x-cls\|s1=pose\|trk=gap1 | jerryg-v8x-cls\|s1=pose\|trk=gap2 | điểm sự kiện | 0 | [0, 0] | hoà (tie) |
| pipeline tốt nhất | jerryg-v8x-cls\|s1=pose\|trk=gap1 | jerryg-v8x-cls\|s1=pose\|trk=gap2 | F1 frame | 0.0000 | [0.0000, 0.0000] | hoà (tie) |
| pipeline tốt nhất | jerryg-v8x-cls\|s1=pose\|trk=gap1 | bertnardo-v8n\|s1=prod\|trk=prod | điểm sự kiện | 2 | [-4, 8] | hoà (tie) |
| pipeline tốt nhất | jerryg-v8x-cls\|s1=pose\|trk=gap1 | bertnardo-v8n\|s1=prod\|trk=prod | F1 frame | 0.0592 | [-0.0629, 0.2422] | hoà (tie) |
| pipeline tốt nhất | jerryg-v8x-cls\|s1=pose\|trk=gap1 | doquanganh-falldetect\|s1=prod\|trk=prod | điểm sự kiện | 4 | [-3, 11] | hoà (tie) |
| pipeline tốt nhất | jerryg-v8x-cls\|s1=pose\|trk=gap1 | doquanganh-falldetect\|s1=prod\|trk=prod | F1 frame | 0.1535 | [0.0311, 0.3500] | khác biệt (different) |
| pipeline tốt nhất | jerryg-v8x-cls\|s1=pose\|trk=gap1 | jerryg-v8x-cls\|s1=prod\|trk=prod | điểm sự kiện | 4 | [1, 8] | khác biệt (different) |
| pipeline tốt nhất | jerryg-v8x-cls\|s1=pose\|trk=gap1 | jerryg-v8x-cls\|s1=prod\|trk=prod | F1 frame | 0.0400 | [-0.0187, 0.1201] | hoà (tie) |
| pipeline tốt nhất | jerryg-v8x-cls\|s1=pose\|trk=gap1 | kamalchibrani-v8\|s1=prod\|trk=prod | điểm sự kiện | 6 | [1, 11] | khác biệt (different) |
| pipeline tốt nhất | jerryg-v8x-cls\|s1=pose\|trk=gap1 | kamalchibrani-v8\|s1=prod\|trk=prod | F1 frame | 0.0105 | [-0.0659, 0.1043] | hoà (tie) |
| pipeline tốt nhất | jerryg-v8x-cls\|s1=pose\|trk=gap1 | khoa05ai-v8m\|s1=prod\|trk=prod | điểm sự kiện | 6 | [0, 12] | hoà (tie) |
| pipeline tốt nhất | jerryg-v8x-cls\|s1=pose\|trk=gap1 | khoa05ai-v8m\|s1=prod\|trk=prod | F1 frame | 0.0098 | [-0.0565, 0.1008] | hoà (tie) |
| pipeline tốt nhất | jerryg-v8x-cls\|s1=pose\|trk=gap1 | leeyunjai-11x\|s1=prod\|trk=prod | điểm sự kiện | 6 | [0, 13] | hoà (tie) |
| pipeline tốt nhất | jerryg-v8x-cls\|s1=pose\|trk=gap1 | leeyunjai-11x\|s1=prod\|trk=prod | F1 frame | 0.0506 | [-0.0381, 0.1440] | hoà (tie) |
| pipeline tốt nhất | jerryg-v8x-cls\|s1=pose\|trk=gap1 | melih-3cls-11n\|s1=prod\|trk=prod | điểm sự kiện | 9 | [3, 14] | khác biệt (different) |
| pipeline tốt nhất | jerryg-v8x-cls\|s1=pose\|trk=gap1 | melih-3cls-11n\|s1=prod\|trk=prod | F1 frame | 0.2280 | [0.1282, 0.3976] | khác biệt (different) |
| pipeline tốt nhất | jerryg-v8x-cls\|s1=pose\|trk=gap1 | pose-rule-yolo11s\|s1=prod\|trk=prod | điểm sự kiện | 7 | [1, 13] | khác biệt (different) |
| pipeline tốt nhất | jerryg-v8x-cls\|s1=pose\|trk=gap1 | pose-rule-yolo11s\|s1=prod\|trk=prod | F1 frame | 0.1964 | [0.0908, 0.3286] | khác biệt (different) |
| pipeline tốt nhất | jerryg-v8x-cls\|s1=pose\|trk=gap1 | syed-le2i-11n\|s1=prod\|trk=prod | điểm sự kiện | 9 | [3, 14] | khác biệt (different) |
| pipeline tốt nhất | jerryg-v8x-cls\|s1=pose\|trk=gap1 | syed-le2i-11n\|s1=prod\|trk=prod | F1 frame | 0.2283 | [0.0613, 0.4657] | khác biệt (different) |
| pipeline tốt nhất | jerryg-v8x-cls\|s1=pose\|trk=gap1 | valentin-ca3o8-v8n\|s1=prod\|trk=prod | điểm sự kiện | 4 | [-2, 10] | hoà (tie) |
| pipeline tốt nhất | jerryg-v8x-cls\|s1=pose\|trk=gap1 | valentin-ca3o8-v8n\|s1=prod\|trk=prod | F1 frame | 0.0463 | [-0.0554, 0.1522] | hoà (tie) |
| Goal 5 | jerryg-ft3\|s1=ft\|trk=gap1 | jerryg-v8x-cls\|s1=pose\|trk=gap1 | điểm sự kiện | -4 | [-12, 5] | hoà (tie) |
| Goal 5 | jerryg-ft3\|s1=ft\|trk=gap1 | jerryg-v8x-cls\|s1=pose\|trk=gap1 | F1 frame | -0.1048 | [-0.2820, 0.0150] | hoà (tie) |
<!-- END GENERATED: paired_all40 -->

## 10. License và hạn chế

- E-FPDS (Maldonado-Bascón et al., Electronics 2019) không ghi license; chỉ dùng để nghiên cứu trong đồ án môn học này
  và sẽ xoá sau môn học. Dữ liệu E-FPDS không được commit. `yolo11s-ft` kế thừa ràng buộc đó cùng AGPL-3.0 của `yolo11s`.
- CAUCAFall: CC BY 4.0 (https://data.mendeley.com/datasets/7w7fccy7ky/4). Tải từ bản mirror công khai trên Kaggle
  `tuyenldvn/caucafall` (8.3 GB) về `benchmark/data/caucafall/` (gitignored).
- Box teacher của stage 1 có một ít nhận nhầm, và nhãn tư thế của clip train do Claude gán bằng mắt.
- `jerryg-ft3` dẫn xuất từ `jerryg-v8x-cls`, vốn không ghi license.
- **Quyết định ngày 2026-10-25 (người dùng), khác non-goal của spec:** hai file weights fine-tune được commit vào repo public
  (`jerryg-ft3` qua Git LFS), dù pipeline không được đề xuất. Dữ liệu huấn luyện vẫn không commit.
- Tập test chỉ có 20 clip (11 clip ngã tính sự kiện), nên CI rộng.

## 11. Tái lập

```
# từ `Fall detection/`
.venv/Scripts/python -I benchmark/finetune/make_split.py --check
.venv/Scripts/python -I benchmark/finetune/prepare_stage1.py --src <thư mục chứa train/valid .tar.gz>
.venv/Scripts/python -I benchmark/finetune/build_stage2_crops.py --source all \
    --caucafall-root benchmark/data/caucafall --review
.venv/Scripts/python -I benchmark/finetune/kaggle_finetune.py bundle|push|status|pull --phase train --user <u>
.venv/Scripts/python -I benchmark/fetch_models.py --only yolo11s-ft,jerryg-ft3
.venv/Scripts/python -I benchmark/run_benchmark.py --stage1-variants pose,ft --models jerryg-v8x-cls,jerryg-ft3 \
    --latency-runs 0 --resume --split test
.venv/Scripts/python -I benchmark/run_benchmark.py --stage1-variants pose,ft --models jerryg-v8x-cls,jerryg-ft3 \
    --latency-only --split test
.venv/Scripts/python -I benchmark/run_benchmark.py --report-only --split test
.venv/Scripts/python -I benchmark/run_benchmark.py --report-only --split all
```
