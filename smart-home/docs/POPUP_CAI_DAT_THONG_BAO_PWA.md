# Popup nhac bat thong bao va cai Smart Home ra man hinh chinh

## Da cap nhat

File duoc sua: `frontend/src/components/QuickActions.tsx`.

- Sau khi **dang nhap** va mo website tren **Android/iPhone**, mot popup duoc hien neu trinh duyet hien tai chua dang ky Web Push **hoac** Smart Home chua chay trong che do ung dung (standalone PWA).
- Chi hien nhung muc chua hoan thanh. Co nut `Bat thong bao ngay`, `Cai ung dung ngay` (khi trinh duyet ho tro), hoac huong dan them vao man hinh chinh.
- Nguoi dung co the bam `De sau` hoac dong popup. Popup se khong lam phien khi chuyen cac trang trong cung phien truy cap; neu tai lai/mo website lan sau va van thieu mot muc thi popup se hien lai.
- Neu da hoan thanh ca hai, popup khong hien. Khi hoan thanh ca hai trong luc dang xem popup, popup tu dong dong.
- Nut `Thong bao` va `Cai ung dung` tren thanh cong cu van duoc giu nguyen o tat ca cac trang.
- Khi quyen thong bao bi chan, website khong the tu mo lai popup xin quyen cua he dieu hanh; giao dien chi huong dan mo cai dat cua trinh duyet de cap lai quyen.

## Cai ban va

1. Giai nen `smart-home-setup-popup-patch.zip` vao thu muc **cha** chua `smart-home` (vd. `D:\smart-home`) va ghi de file frontend. Khong xoa `.env`, `.venv`, database hoac models.
2. Tu PowerShell, tai `D:\smart-home\smart-home`, build lai frontend:

```powershell
.\BUILD_FRONTEND.bat
```

Neu khong su dung file bat tren:

```powershell
docker compose up -d --build dashboard
```

3. Backend FastAPI khong can sua hay cai lai. Neu can khoi dong lai toan he thong, chay:

```powershell
.\START_NGROK.bat
```

4. Mo URL HTTPS cua ngrok tren dien thoai, dang nhap dashboard va tai lai trang. Luu y: prompt duoc tu dong hien tren **thiet bi di dong**; desktop van co hai nut tren thanh cong cu.

## Android

1. Truy cap Smart Home qua Chrome va dang nhap.
2. Khi popup hien, nhan `Bat thong bao ngay` va `Cho phep` neu trinh duyet hoi.
3. Nhan `Cai ung dung ngay` neu co. Neu khong, chon menu Chrome `⋮` → `Cai dat ung dung` / `Them vao man hinh chinh`.
4. Mo Smart Home tu bieu tuong tren man hinh chinh. Sau khi da bat Push va chay trong PWA, popup se khong hien nua.

## iPhone (iOS 16.4+)

1. Truy cap Smart Home qua HTTPS va dang nhap bang Safari.
2. Nhan `Xem cach them vao man hinh chinh`, sau do thao tac thu cong: `Chia se` → `Them vao Man hinh chinh`.
3. Mo Smart Home **tu bieu tuong PWA** moi tao, khong phai tab Safari.
4. Khi popup hien lai, nhan `Bat thong bao ngay` va cho phep thong bao.

Apple khong cung cap API de website ep ghim icon ra man hinh chinh; thao tac tren iPhone phai do nguoi dung thuc hien.

## Luu y

- Website phai phuc vu qua HTTPS (ngoai `localhost`) va backend phai cau hinh VAPID cho Web Push.
- Neu ngrok doi domain, can mo domain moi va dang ky thong bao lai cho domain do.
- Trang web khong the biet chac mot PWA da cai dat neu nguoi dung dang mo no trong tab trinh duyet thong thuong. Trang thai `da cai` duoc xac nhan khi dang chay tu bieu tuong PWA (standalone).
- Popup khong tu dong goi `Notification.requestPermission()`; yeu cau quyen chi xuat hien sau thao tac `Bat thong bao ngay` cua nguoi dung.
- Khong dung Push lam kenh canh bao an toan duy nhat: he dieu hanh co the tre/chan thong bao.

## Kiem tra nhanh

1. Dien thoai chua cai PWA, chua bat Push: popup hien ca 2 muc.
2. Da bat Push nhung chua mo bang PWA: popup chi hien muc cai PWA.
3. Da mo PWA nhung chua bat Push: popup chi hien muc bat Push.
4. Da hoan thanh 2 muc: khong hien popup.
5. Bam `De sau` va chuyen trang: khong tu hien lai. Tai lai trang/mo moi: nhac lai neu con muc chua xong.
6. Quyền thong bao `denied`: hien huong dan cap lai quyen, khong lap lai yeu cau quyen he dieu hanh.
