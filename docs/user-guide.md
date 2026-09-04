# Finance & US Stock Market Tool: User Guide

Welcome to the Finance & US Stock Market Tracking CLI tool. This guide provides step-by-step instructions and explanations for every feature included in the application, designed to help you track market conditions, analyze assets, manage your portfolio, and maximize investment returns.

---

## Table of Contents
1. [Installation & Setup](#1-installation--setup)
2. [Setting Up API Keys](#2-setting-up-api-keys)
3. [Personal Finance Tracking](#3-personal-finance-tracking)
4. [US Stock Market Quotes & Analysis](#4-us-stock-market-quotes--analysis)
5. [Portfolio Tracking & MPT Optimization](#5-portfolio-tracking--mpt-optimization)
6. [Strategy Backtesting](#6-strategy-backtesting)
7. [Multi-Factor Stock Screener](#7-multi-factor-stock-screener)
8. [Macroeconomic Dashboard (FRED)](#8-macroeconomic-dashboard-fred)
9. [Automated Market Briefing Reports](#9-automated-market-briefing-reports)
10. [Session Wrap-Up & Memory Management](#10-session-wrap-up--memory-management)

---

## 1. Installation & Setup

### What it is & How it's used
Before using the tool, you need to install the Python package locally in your environment. This registers the `finance` command-line executable globally in your terminal.

### Step-by-Step Instructions
Open your terminal in the project root directory and run:
```bash
pip install -e .[dev]
```
To verify installation:
```bash
finance --version
```

---

## 2. Setting Up API Keys

### What it is & How it's used
The application fetches real-time market data from **Alpha Vantage** and macroeconomic indicators from **FRED (Federal Reserve Economic Data)**. For security, API keys are read strictly from environment variables and are automatically redacted from logs.

### Step-by-Step Instructions
Set your API keys in your terminal session:

* **Windows (PowerShell):**
  ```powershell
  $env:ALPHA_VANTAGE_API_KEY="your_alpha_vantage_key"
  $env:FRED_API_KEY="your_fred_key"
  ```
* **Windows (Command Prompt):**
  ```cmd
  set ALPHA_VANTAGE_API_KEY=your_alpha_vantage_key
  set FRED_API_KEY=your_fred_key
  ```
* **macOS / Linux (Bash/Zsh):**
  ```bash
  export ALPHA_VANTAGE_API_KEY="your_alpha_vantage_key"
  export FRED_API_KEY="your_fred_key"
  ```

---

## 3. Personal Finance Tracking

### What it is & How it's used
This section allows you to log and monitor personal income and expense transactions (`finance.json`), giving you an instant overview of your net cash flow and balance.

### Step-by-Step Instructions
* **Add Income:**
  ```bash
  finance add income 5000.00 "Salary" --date 2026-09-01
  ```
* **Add Expense:**
  ```bash
  finance add expense 1200.00 "Rent" --date 2026-09-02
  ```
* **List All Transactions:**
  ```bash
  finance list
  ```
* **View Financial Summary:**
  ```bash
  finance summary
  ```

---

## 4. US Stock Market Quotes & Analysis

### What it is & How it's used
Track live quotes and conduct deep technical indicator analysis (Simple Moving Averages, RSI, volatility, and bullish/bearish trend scores) for indices (S&P 500 `SPY` / `^GSPC`, Dow Jones `DIA` / `^DJI`) and individual stocks.

### Step-by-Step Instructions
* **Get a Real-Time Quote:**
  ```bash
  finance market quote SPY
  ```
* **Run Technical Indicator Analysis:**
  ```bash
  finance market analyze AAPL
  ```
  *(Calculates 20, 50, and 200-day SMAs, 14-day RSI with overbought/oversold signals, annualized volatility, and overall trend score).*

---

## 5. Portfolio Tracking & MPT Optimization

### What it is & How it's used
Track your stock holdings, cost basis, unrealized P&L, and market valuations (`portfolio.json`). Furthermore, use **Modern Portfolio Theory (Mean-Variance Optimization)** to calculate optimal asset allocation weights that maximize your portfolio's Sharpe ratio.

### Step-by-Step Instructions
* **Add a Stock Position:**
  ```bash
  finance portfolio add SPY 10 400.00
  finance portfolio add AAPL 15 180.00
  ```
* **List Positions:**
  ```bash
  finance portfolio list
  ```
* **View Valuation & P&L Summary:**
  ```bash
  finance portfolio summary
  ```
* **Run MPT Portfolio Optimization:**
  ```bash
  finance optimize --rf 0.04
  ```
  *(Calculates expected annual return, annualized volatility, and optimal percentage weights for your holdings).*

---

## 6. Strategy Backtesting

### What it is & How it's used
Test trading strategies (such as Simple Moving Average crossovers) against historical price data before risking real capital. Compares strategy returns against buy-and-hold benchmarks.

### Step-by-Step Instructions
* **Run SMA Crossover Backtest:**
  ```bash
  finance backtest SPY --fast 20 --slow 50
  ```

---

## 7. Multi-Factor Stock Screener

### What it is & How it's used
Screens a universe of top stocks across multiple quantitative factors (3-month momentum, 1-month momentum, and annualized volatility) to rank and surface top investment opportunities.

### Step-by-Step Instructions
* **Run Screener:**
  ```bash
  finance screen
  ```

---

## 8. Macroeconomic Dashboard (FRED)

### What it is & How it's used
Pulls key macroeconomic indicators from the Federal Reserve Economic Data (FRED) database to evaluate broader monetary conditions, interest rates, and inflation.

### Step-by-Step Instructions
* **View Core Macro Dashboard (Fed Funds Rate, 10-Year Treasury Yield, CPI Inflation, Unemployment):**
  ```bash
  finance macro overview
  ```
* **Query Any Custom FRED Series ID:**
  ```bash
  finance macro series DGS10
  ```

---

## 9. Automated Market Briefing Reports

### What it is & How it's used
Compiles a consolidated briefing report combining macroeconomic indicators, market ticker technicals, portfolio valuations, and optimal asset allocations into a single view.

### Step-by-Step Instructions
* **Generate Market Briefing:**
  ```bash
  finance report
  ```

---

## 10. Session Wrap-Up & Memory Management

### What it is & How it's used
The **wrap-up** command concludes your working session by summarizing financial status, generating a dynamic "What's Next" roadmap, updating `progress.md`, and clearing short-term session memory.

### Step-by-Step Instructions
* **Execute Session Wrap-Up:**
  ```bash
  finance wrap-up
  ```
* **Manage In-Context Memory:**
  ```bash
  finance memory show
  finance memory remember risk_profile "moderate"
  finance memory recall
  ```
