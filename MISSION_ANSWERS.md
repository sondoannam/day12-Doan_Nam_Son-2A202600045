# Day 12 Lab - Mission Answers

## Part 1: Localhost vs Production

### Exercise 1.1: Anti-patterns found
1. **Hardcoded Secrets:** Các thông tin nhạy cảm như `OPENAI_API_KEY` và `DATABASE_URL` được gắn cứng trực tiếp vào source code, nguy cơ lộ variables rất cao nếu đẩy lên các repository công khai.
2. **Thiếu Configuration Management:** Các thiết lập môi trường (như `DEBUG = True`, `MAX_TOKENS = 500`) bị gán cứng thay vì đọc từ các biến môi trường (Environment Variables), gây khó khăn khi muốn thay đổi cấu hình giữa dev/staging/production.
3. **Sử dụng lệnh `print()` thay cho Structured Logging:** Dùng `print()` không lưu lại định dạng chuẩn xác (như JSON), gây khó khăn cho việc giám sát log trên hệ thống. Tệ hại hơn, log còn in luôn cả API Key bí mật ra ngoài màn hình console .
4. **Không có Health Check Endpoints (Liveness/Readiness probes):** Thiếu các endpoint `/health` hoặc `/ready`. Nếu agent bị crash hoặc treo, nền tảng Cloud (như Docker/Kubernetes) sẽ mù tịt, không biết để tự động khởi động lại container.
5. **Gán cứng cấu hình Network trong Entry Point:** Thiết lập `host="localhost"` và `port=8000` khiến ứng dụng không thể nhận các kết nối từ bên ngoài container. Ngoài ra, việc bật `reload=True` chỉ dành cho môi trường phát triển, nếu mang lên production sẽ gây lãng phí tài nguyên và tiềm ẩn rủi ro.


### Exercise 1.3: Comparison table
| Feature | Develop | Production | Why Important? |
|---------|---------|------------|----------------|
| Config & Secrets | Hardcode trực tiếp trong code. | Đọc từ biến môi trường (Environment Variables) qua file cấu hình. | Dễ dàng thay đổi cấu hình giữa các môi trường (Dev/Prod), bảo mật thông tin (không vô tình commit API Key lên Git). |
| Port & Network | Cố định `port=8000` và `host="localhost"`. | Đọc từ biến `PORT`, bind vào `host="0.0.0.0"`. | Trên Cloud (Railway/Render), hệ thống tự cấp phát Port động. Bind `0.0.0.0` để container có thể nhận traffic từ bên ngoài mạng. |
| Health Check | Không có endpoint nào để kiểm tra. | Có các endpoint `/health` (Liveness) và `/ready` (Readiness). | Giúp Cloud Platform biết container còn sống hay không để tự động khởi động lại, và Load Balancer biết khi nào an toàn để điều hướng traffic. |
| Logging | Dùng hàm `print()` đơn giản. | Dùng thư viện `logging` xuất ra chuẩn JSON có cấu trúc (Structured Logging). | Định dạng chuẩn giúp dễ dàng tìm kiếm, lọc và phân tích log trên các hệ thống quản lý tập trung (như Datadog, ELK). |
| Shutdown | Tắt đột ngột, hủy diệt tiến trình ngay lập tức. | Bắt tín hiệu `SIGTERM`, chờ xử lý xong request hiện tại (Graceful Shutdown). | Tránh làm mất mát dữ liệu hoặc gây lỗi cho người dùng đang gọi API dở dang khi hệ thống cần cập nhật hoặc tắt bớt container. |
...

## Part 2: Docker

### Exercise 2.1: Dockerfile questions
1. Base image: Base image trong Dockerfile là lớp nền tảng (image gốc) được chỉ định bởi câu lệnh FROM, đóng vai trò là hệ điều hành hoặc môi trường runtime cơ bản để xây dựng một Docker image mới. Ở đây là `python3.11`
2. Working directory: là một chỉ thị (instruction) được sử dụng để thiết lập thư mục làm việc hiện tại cho các lệnh tiếp theo như RUN, CMD, ENTRYPOINT, COPY, và ADD. Ở đây là `/app`
3. Why copy `requirements.txt` first: Để tận dụng cache của Docker. Nếu `requirements.txt` không thay đổi, Docker sẽ cache bước cài đặt dependencies, giúp build nhanh hơn khi chỉ thay đổi code. Và nếu không copy file `requirements.txt` trước, thì lệnh `pip install` sau sẽ không chạy được
4. CMD vs ENTRYPOINT: `CMD` cung cấp lệnh mặc định có thể bị ghi đè khi chạy container, trong khi `ENTRYPOINT` xác định lệnh cố định không thể bị thay đổi. Sử dụng `ENTRYPOINT` giúp đảm bảo rằng ứng dụng luôn chạy đúng cách, bất kể tham số nào được truyền vào khi khởi động container.

### Exercise 2.3: Image size comparison
- Develop: 1.67 GB
- Production: 262 MB
- Difference: 84.68%

## Part 3: Cloud Deployment

### Exercise 3.1: Railway deployment
- URL: https://your-app.railway.app
- Screenshot: [Link to screenshot in repo]

## Part 4: API Security

### Exercise 4.1-4.3: Test results
[Paste your test outputs]

### Exercise 4.4: Cost guard implementation
[Explain your approach]

## Part 5: Scaling & Reliability

### Exercise 5.1-5.5: Implementation notes
[Your explanations and test results]