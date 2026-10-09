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
