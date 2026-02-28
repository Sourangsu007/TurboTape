# Trading Dashboard

A comprehensive, full-stack stock analysis platform designed for Indian markets. This application combines fundamental screening, technical analysis, and automated decision-making into a unified, premium dashboard.

## 🚀 Key Features

- **Intuitive Watchlist Management**: Easily add stocks manually or import them in bulk via CSV, XLS, or XLSX files.
- **Automated Investment Decisions**: Get clear **Buy**, **Add**, or **Sell** recommendations for any stock, backed by concise, human-readable reasoning.
- **Deep Technical Analysis**: View a snapshot of critical indicators including Moving Averages (SMA/EMA), RSI, ADX (Trend Strength), Parabolic SAR, SuperTrend, and Donchian Channels.
- **Fundamental Screening**: Automatically fetch 30+ financial metrics (Sales Growth, Profit Margin, Debt/Equity, etc.) from multiple data sources.
- **Market Stage Analysis**: Understand where a stock sits in its lifecycle (Accumulation, Markup, Distribution, or Decline).
- **Comparative Ranking**: Perform batch analysis on your entire watchlist to identify the strongest opportunities based on calculated scores and justifications.
- **Resilient Infrastructure**: Built with a multi-provider fallback system to ensure 99.9% uptime for data fetching and analysis.
- **Performant Caching**: Intelligent two-layer disk caching ensures lightning-fast load times for previously analyzed stocks while respecting API rate limits.
- **Live Raw Data View**: Inspect the exact financial data points fetched for any stock directly from the dashboard.
- **Individual Row Controls**: Re-analyze specific stocks or reset their cache with a single click (⚡/🧹).

## 🛠️ Technology Stack

### Backend
- **FastAPI**: High-performance Python framework for building APIs.
- **LiteLLM**: Unified interface for multi-provider LLM orchestration.
- **DiskCache**: Persistent, file-based caching system.
- **YFinance & Custom Scrapers**: Robust data retrieval from multiple financial providers.

### Frontend
- **React**: Modern, component-based user interface.
- **Vite**: Ultra-fast build tool and development server.
- **Vanilla CSS**: Premium, responsive glassmorphism design system.
- **SheetJS**: Client-side spreadsheet processing.

---

## 🚦 Getting Started

### Prerequisites
- Python 3.10+
- Node.js 18+
- API Keys for supported providers (Gemini, Groq, etc.) defined in a `.env` file.

### Backend Setup
1. Navigate to the `API` directory.
2. Install dependencies: `uv sync` or `pip install -r requirements.txt`.
3. Start the server: `python -m uv run uvicorn main:app --port 8000`.

### Frontend Setup
1. Navigate to the `UI` directory.
2. Install dependencies: `npm install`.
3. Start the dev server: `npm run dev`.

---

*Disclaimer: This tool is for educational and analytical purposes only. Always perform your own due diligence before making investment decisions.*
