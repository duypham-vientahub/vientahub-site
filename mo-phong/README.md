# Mô phỏng phản ứng chính sách

Trang `/mo-phong/` do app Synthetic Population Studio đăng tự động. Không sửa tay các file trong thư mục này.

- `index.html`: trang xem tương tác. CSP có hash của script; app tự tính lại khi cập nhật.
- `reports.json`: danh sách báo cáo (`listed: false` là báo cáo chỉ ai có link mới xem được).
- `r/<slug>.json`: số liệu tổng hợp của một báo cáo. Không có dữ liệu từng persona; nhóm dưới 30 câu trả lời bị bỏ.

Gỡ một báo cáo: dùng nút "Gỡ khỏi website" trong app, app sẽ xoá file JSON và dòng tương ứng.
