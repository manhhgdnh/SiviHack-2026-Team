# Kiến trúc hệ thống tham chiếu

Đây không phải architecture cố định.

Architecture thực tế sẽ được điều chỉnh theo Challenge.

---

# Architecture mặc định

User
↓
Frontend
↓
Backend API
↓
AI / Data
↓
Validation
↓
Business / Quantitative Logic
↓
Decision
↓
n8n / External API
↓
Action
↓
Frontend Result

---

# Frontend

Trách nhiệm:
- Input
- Upload
- User interaction
- Visualization
- Result display
- Action buttons

---

# Backend

Trách nhiệm:
- API
- File processing
- Database
- AI integration
- Service integration
- Deployment
- Error handling

---

# AI / Data / Decision

Trách nhiệm:
- LLM
- RAG
- ML
- Extraction
- Validation
- Scoring
- Ranking
- Forecasting
- Optimization
- Evaluation

---

# Automation

Trách nhiệm:
- n8n
- Webhook
- External API
- Email
- Notification
- Business actions
- Workflow automation

---

# AI pipeline ưu tiên

Input
↓
Extraction / Retrieval
↓
Structured Data
↓
Validation
↓
Quantitative / Business Logic
↓
Decision
↓
Evidence / Confidence
↓
Action
