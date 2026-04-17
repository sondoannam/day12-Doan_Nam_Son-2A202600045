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

### Exercise 3.2: Render deployment
- URL: https://ai-agent-bgwm.onrender.com/
- Screenshot: ![render-deployment](screenshots/render-deployment.png)

## Part 4: API Security

### Exercise 4.1-4.3: Test results

```bash
#  Không có key
curl http://localhost:8000/ask -X POST \
  -H "Content-Type: application/json" \
  -d '{"question": "Hello"}'
Result: {"detail":"Missing API key. Include header: X-API-Key: <your-key>"}

#  Có key
curl http://localhost:8000/ask -X POST \
  -H "X-API-Key: demo-key-change-in-production" \
  -H "Content-Type: application/json" \
  -d '{"question": "Hello"}'
Result: {
    "question": "Hello",
    "answer": "Agent đang hoạt động tốt! (mock response) Hỏi thêm câu hỏi đi nhé."
}

# JWT authentication 
TOKEN="eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJ0ZWFjaGVyIiwicm9sZSI6ImFkbWluIiwiaWF0IjoxNzc2NDIzODEzLCJleHAiOjE3NzY0Mjc0MTN9.9ZC95TVva6f9NLvGNQwHuJsaqp2iQlg-999k6W3hPwY"
curl http://localhost:8000/ask -X POST \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"question": "Explain JWT"}'
result: {
    "question": "Explain JWT",
    "answer": "Tôi là AI agent được deploy lên cloud. Câu hỏi của bạn đã được nhận.",
    "usage": {
        "requests_remaining": 99,
        "budget_remaining_usd": 1.9e-05
    }
}

# Rate limiting
for i in {1..20}; do
  curl http://localhost:8000/ask -X POST \
    -H "Authorization: Bearer $TOKEN" \
    -H "Content-Type: application/json" \
    -d '{"question": "Test '$i'"}'
  echo ""
done
result: {"detail":{"error":"Rate limit exceeded","limit":100,"window_seconds":60,"retry_after_seconds":12}}

```

### Exercise 4.4: Cost guard implementation
Cách tiếp cận (Approach) để bảo vệ chi phí API (Cost Guard) được chia làm 2 pha rõ rệt: Tiền kiểm và Hậu kiểm.

1. **Định giá (Pricing & Tracking):** Hệ thống không đếm số lượng request một cách mù quáng, mà tính toán chi phí (USD) dựa trên số token đầu vào (input) và đầu ra (output) thực tế theo bảng giá của model LLM (VD: GPT-4o-mini).
2. **Tiền kiểm (`check_budget`):** Trước khi cho phép user gọi LLM, hệ thống sẽ kiểm tra xem chi phí tích lũy trong kỳ của user đó đã vượt ngân sách chưa. Nếu vượt, lập tức chặn đứng và ném ra lỗi HTTP 402 (Payment Required). Đồng thời, hệ thống cũng có một Global Budget để chặn toàn bộ traffic (HTTP 503) nếu tổng chi phí cả hệ thống vượt ngưỡng, tránh rủi ro phá sản.
3. **Hậu kiểm và Ghi nhận (`record_usage`):** Sau khi nhận response từ LLM, hệ thống tính toán chính xác số token đã tiêu thụ, quy đổi ra tiền và cộng dồn vào tổng chi của user trong ngày.

## Part 5: Scaling & Reliability

### Exercise 5.1-5.5: Implementation notes

**1. Health Checks & Graceful Shutdown (Ex 5.1 & 5.2):**
- Đã sử dụng endpoint `/health` để hệ thống theo dõi liveness và `/ready` cho readiness. 
- Graceful shutdown được thiết lập thông qua việc bắt tín hiệu `SIGTERM`, cho phép uvicorn hoàn thành các in-flight requests trước khi tắt hẳn.
- **Test Output:**
```bash
curl http://localhost:8000/health
result: 200 OK

curl http://localhost:8000/ready
result: 200 OK

curl http://localhost:8000/ask -X POST -H "Content-Type: application/json" -d '{"question": "Long task"}' & sleep 1; kill -TERM 59709
result:
127.0.0.1:52074 - "POST /ask HTTP/1.1" 422 Unprocessable Entity
INFO:     Shutting down
INFO:     Waiting for application shutdown.
2026-04-17 17:21:56,344 INFO 🔄 Graceful shutdown initiated...
2026-04-17 17:21:56,344 INFO ✅ Shutdown complete
INFO:     Application shutdown complete.
INFO:     Finished server process [59709]
2026-04-17 17:21:56,344 INFO Received signal 15 — uvicorn will handle graceful shutdown
```

**2. Stateless Design (Ex 5.3):**
- Để có thể scale ra nhiều instances mà không làm mất context (lịch sử chat) của user, trạng thái ứng dụng (state) đã được tách rời khỏi bộ nhớ (in-memory) và chuyển sang lưu trữ tập trung tại Redis.

**3. Load Balancing (Ex 5.4):**
- Nginx được sử dụng làm Load Balancer để phân phối đều traffic (round-robin) đến các instances của agent.
- **Test Output:**
```bash
for i in {1..10}; do     
  curl http://localhost:8080/chat -X POST \
    -H "Content-Type: application/json" \
    -d '{"question": "Request '$i'"}'
done
result:
agent-1  | INFO:     172.18.0.6:40764 - "POST /chat HTTP/1.1" 200 OK
agent-1  | INFO:     172.18.0.6:40764 - "POST /chat HTTP/1.1" 200 OK
agent-1  | INFO:     172.18.0.6:40764 - "POST /chat HTTP/1.1" 200 OK
agent-1  | INFO:     172.18.0.6:40764 - "POST /chat HTTP/1.1" 200 OK
agent-2  | INFO:     172.18.0.6:54392 - "POST /ask HTTP/1.1" 404 Not Found
agent-2  | INFO:     127.0.0.1:45836 - "GET /health HTTP/1.1" 200 OK
agent-2  | INFO:     172.18.0.6:40906 - "POST /chat HTTP/1.1" 200 OK
agent-2  | INFO:     172.18.0.6:40906 - "POST /chat HTTP/1.1" 200 OK
agent-2  | INFO:     172.18.0.6:40906 - "POST /chat HTTP/1.1" 200 OK
agent-2  | INFO:     127.0.0.1:35542 - "GET /health HTTP/1.1" 200 OK
agent-2  | INFO:     127.0.0.1:51080 - "GET /health HTTP/1.1" 200 OK
agent-2  | INFO:     127.0.0.1:40236 - "GET /health HTTP/1.1" 200 OK
agent-2  | INFO:     127.0.0.1:52244 - "GET /health HTTP/1.1" 200 OK
agent-2  | INFO:     127.0.0.1:55654 - "GET /health HTTP/1.1" 200 OK
agent-2  | INFO:     127.0.0.1:34294 - "GET /health HTTP/1.1" 200 OK
agent-2  | INFO:     127.0.0.1:60054 - "GET /health HTTP/1.1" 200 OK
agent-2  | INFO:     127.0.0.1:58094 - "GET /health HTTP/1.1" 200 OK
agent-2  | INFO:     127.0.0.1:41272 - "GET /health HTTP/1.1" 200 OK
agent-2  | INFO:     127.0.0.1:35166 - "GET /health HTTP/1.1" 200 OK
agent-2  | INFO:     127.0.0.1:54420 - "GET /health HTTP/1.1" 200 OK
agent-2  | INFO:     127.0.0.1:57484 - "GET /health HTTP/1.1" 200 OK
agent-2  | INFO:     127.0.0.1:52128 - "GET /health HTTP/1.1" 200 OK
agent-2  | INFO:     127.0.0.1:42584 - "GET /health HTTP/1.1" 200 OK
agent-2  | INFO:     172.18.0.6:49028 - "POST /chat HTTP/1.1" 200 OK
agent-2  | INFO:     172.18.0.6:49028 - "POST /chat HTTP/1.1" 200 OK
agent-2  | INFO:     172.18.0.6:49028 - "POST /chat HTTP/1.1" 200 OK
```

**4. Test Stateless (Ex 5.5):**
Chạy lệnh `docker compose up --scale agent=3` và `python test_stateless.py`, kết quả cho thấy các request trong cùng một session được phục vụ bởi các instances khác nhau nhưng lịch sử trò chuyện vẫn nhất quán:
```bash
❯ python test_stateless.py
============================================================
Stateless Scaling Demo
============================================================

Session ID: fb63959a-60f1-4f14-8181-14ede41e02a5

Request 1: [instance-9f25e6]
  Q: What is Docker?
  A: Container là cách đóng gói app để chạy ở mọi nơi. Build once, run anywhere!...

Request 2: [instance-a59fad]
  Q: Why do we need containers?
  A: Đây là câu trả lời từ AI agent (mock). Trong production, đây sẽ là response từ O...

Request 3: [instance-62d1d9]
  Q: What is Kubernetes?
  A: Đây là câu trả lời từ AI agent (mock). Trong production, đây sẽ là response từ O...

Request 4: [instance-9f25e6]
  Q: How does load balancing work?
  A: Agent đang hoạt động tốt! (mock response) Hỏi thêm câu hỏi đi nhé....

Request 5: [instance-a59fad]
  Q: What is Redis used for?
  A: Tôi là AI agent được deploy lên cloud. Câu hỏi của bạn đã được nhận....

------------------------------------------------------------
Total requests: 5
Instances used: {'instance-62d1d9', 'instance-a59fad', 'instance-9f25e6'}
✅ All requests served despite different instances!

--- Conversation History ---
Total messages: 10
  [user]: What is Docker?...
  [assistant]: Container là cách đóng gói app để chạy ở mọi nơi. Build once...
  [user]: Why do we need containers?...
  [assistant]: Đây là câu trả lời từ AI agent (mock). Trong production, đây...
  [user]: What is Kubernetes?...
  [assistant]: Đây là câu trả lời từ AI agent (mock). Trong production, đây...
  [user]: How does load balancing work?...
  [assistant]: Agent đang hoạt động tốt! (mock response) Hỏi thêm câu hỏi đ...
  [user]: What is Redis used for?...
  [assistant]: Tôi là AI agent được deploy lên cloud. Câu hỏi của bạn đã đư...

✅ Session history preserved across all instances via Redis!
```
