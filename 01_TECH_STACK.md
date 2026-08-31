# Tech Stack SiviHack 2026

## Nguyên tắc lựa chọn

Ưu tiên theo thứ tự:

1. Tốc độ phát triển
2. Độ ổn định
3. Dễ integration
4. Dễ deploy
5. Dễ demo
6. Team đã có kinh nghiệm sử dụng

Không đưa công nghệ mới vào trong Hackathon trừ khi:

- Challenge bắt buộc;
- Stack hiện tại không giải quyết được bài toán;
- Lợi ích lớn hơn rõ ràng so với chi phí học và integration.

---

# Frontend

Công nghệ chính:
- Next.js / React

Phương án dự phòng:
- Streamlit

Các chức năng thường cần:
- File upload
- Form input
- Dashboard
- Table
- Chart
- Result cards
- Evidence/source display
- Loading state
- Error state
- Action buttons

---

# Backend

Công nghệ chính:
- Python
- FastAPI

Trách nhiệm:
- REST API
- File upload
- Data processing
- Gọi AI service
- Gọi external API
- Database
- Error handling
- Logging
- Deployment

---

# AI / Data / Quant

Ngôn ngữ:
Python

Libraries chính:
- pandas
- numpy
- scikit-learn
- pydantic

LLM chính:
OpenAI hoặc Claude


Các capability có thể dùng:
- Structured extraction
- RAG
- Document analysis
- Classification
- Recommendation
- Ranking
- Risk scoring
- Forecasting
- Anomaly detection
- Tool calling
- Optimization

---

# Workflow Automation

Công nghệ:
n8n Cloud

Use cases:
- Webhook
- HTTP Request
- External API
- Email
- Notification
- Database action
- Workflow orchestration
- Business action

---

# Database

Công nghệ chính:
Supabase / PostgreSQL

Phương án đơn giản:
SQLite

---

# Deployment

Frontend:
[Điền]

Backend:
[Điền]

Database:
Supabase

Workflow:
n8n Cloud

---

# Version Control

GitHub

Branches:

main
→ phiên bản ổn định

dev
→ integration

feature/*
→ chức năng riêng

fix/*
→ sửa lỗi

---

# Quy tắc

Không thay đổi stack giữa cuộc thi nếu không có lý do đủ mạnh.
