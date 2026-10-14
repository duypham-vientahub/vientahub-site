# Market Pulse — cách cập nhật

Trang `/thi-truong/` chỉ đọc `data.json`. Mỗi lần cập nhật chỉ sửa `data.json`, không sửa `index.html`.

## Các trường trong data.json

| Trường | Nội dung |
|---|---|
| `updated`, `updatedISO`, `asOf`, `week` | Thời điểm cập nhật (GMT+7), ngày dữ liệu đóng cửa, tuần trong năm |
| `headline`, `lede` | Kết luận một câu và đoạn mở đầu. `**chữ đậm**` được hỗ trợ |
| `regimeLabel`, `regime[]` | Nhãn chế độ vĩ mô và các cặp `[nhãn, giá trị]` |
| `chain[]` | Chuỗi truyền dẫn vĩ mô `{t, v}`, 4–6 mắt xích |
| `flowsNote`, `flowsIn[]`, `flowsOut[]` | Dòng tiền `{k, q, e}`: tên, con số, giải thích |
| `groups[]`, `markets[]` | Bảng thị trường `{name, sub, g, last, m1, ytd, est?, sig, lv}`; `m1`, `ytd` là số %, `null` nếu thiếu; `est: true` khi YTD là ước tính |
| `feature` | Chủ đề nổi bật / kiểm chứng: `{eyebrow, title, tag, lv, text, claims[{t, lv, tag, yes[], no[]}]}` |
| `vnTitle`, `vn[]`, `vnNote` | Việt Nam `{k, v, d}` |
| `strategy` | `{title, note, items[{a, s, lv, why, flip}]}`: lớp tài sản, định hướng, lý do, điều kiện đổi hướng |
| `scenTitle`, `scen[]` | Kịch bản `{t, lv, p, b[]}` |
| `cal[]` | Lịch `[ngày, sự kiện]`, bỏ các mốc đã qua |
| `sources[]` | `[nhãn, url]` cho mọi số liệu |
| `disclaimer` | Luôn ghi rõ không phải khuyến nghị đầu tư |

`lv` nhận `up` (xanh), `down` (đỏ), `warn` (vàng), `info` (xám).

## Nguyên tắc nội dung

- Mọi con số có nguồn và ngày. Ước tính ghi `~`.
- Trình bày dữ liệu trước, kết luận sau. Mỗi luận điểm có mặt trái.
- Chiến lược và kịch bản là ý kiến phân tích, không phải khuyến nghị.
- Viết tiếng Việt ngắn, rõ, người không chuyên đọc được.

## Mô phỏng 3 tháng (`sim/`)

- `sim/run_sim.py` chạy bằng GitHub Actions (`.github/workflows/market-sim.yml`) lúc 06:40 mỗi ngày và mỗi khi `sim/config.json` đổi trên `main`; kết quả ghi vào `sim/sim.json`.
- Mô hình: GJR-GARCH(1,1) phần dư skew-t cho từng tài sản, liên kết bằng Filtered Historical Simulation, cộng lớp kịch bản vĩ mô; kiểm định ngoài mẫu độ phủ dải 5–95%.
- Phân tích hằng ngày chỉ sửa phần `scenarios` trong `sim/config.json` (xác suất, cú sốc, nguồn giả định) và trường `simNote` trong `data.json` (2–3 câu đọc kết quả). Không sửa `sim.json` bằng tay.

## Bảng thị trường và kịch bản theo thị trường

- `sim/market.json` (Actions tạo): giá thật và chỉ báo tự tính cho ~30 tài sản (1 phiên, 1 tuần, 1 tháng, 3 tháng, YTD, cách đỉnh 52 tuần, MA50/MA200, xu hướng, RSI14, biến động 20 phiên, 60 phiên gần nhất). Danh sách tài sản: `assets` + `stats_only` trong `sim/config.json`.
- `data.json > marketNotes`: nhận định ngắn theo `id` tài sản cho cột "Nhận định".
- `data.json > scenarioGuide`: `intro`, `beginnerGeneral[]`, `disclaimer`, `markets[{id, summary, scen:{base|deal|shock:{what, signs}}, beginner[]}]`. Id kịch bản phải trùng `sim/config.json > scenarios.list[].id`. Biểu đồ và con số mỗi kịch bản lấy tự động từ `sim.json > assets[].byScenario`.
- Gợi ý cho người mới là nguyên tắc chung, viết dễ hiểu, không nêu mã cụ thể để mua, không phải tư vấn cá nhân.

## Bộ lọc mã tiềm năng (`sim/screener.py`)

- Chạy cùng workflow mô phỏng (bước "Run screener", lỗi không chặn mô phỏng); ghi `sim/screener.json`. Không sửa tay.
- Danh sách mã và ngưỡng: `sim/screener_config.json` (Việt Nam qua VNDirect/VPS/SSI, Mỹ và crypto qua Yahoo).
- Khung lọc: cổng thị trường (MA50 có vùng đệm, EMA20, phiên phân phối) → tầng 1 thanh khoản 20 phiên → tầng 2 điểm RS thang 6 (RS 3T dương 2đ, RS 6T dương 1đ, giữ giá phiên chỉ số giảm 2đ, cùng ngành mạnh 1đ; đạt từ 4) → tầng 3 U/D volume 50 phiên ≥ 1 và giá trên MA50.
- `data.json > screener`: `title`, `intro`, `method[]`, `disclaimer`, `notes.{vn|us|crypto}` = `{asOf, verdict, points[], action?, picks[]?}`. `picks` là mã phòng đầu tư chấm tay: `{code, name, sector, price, verdict, lv, summary, levels[[nhãn, giá, ghi chú]], pros[], cons[], planNote}`. Phân tích hằng ngày cập nhật `notes` cho khớp với `screener.json` mới nhất.
