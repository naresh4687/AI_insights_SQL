# InsightSQL — Demo Script

About 8 minutes. The figures below come from the deterministic sample data, so they are
the same on every machine.

## Before the demo

```bash
source .venv/bin/activate
python scripts/seed_database.py     # fresh data and empty history
streamlit run app.py                # open http://localhost:8501
```

For part 4 (AI Mode), set `GEMINI_API_KEY` in `.env` before starting the app. Without a
key or internet, show part 4b instead.

## 1. The problem (30 s)

> "Business users have questions about their sales data but can't write SQL. InsightSQL
> lets them ask in plain English and shows the answer, the SQL behind it, and a chart,
> without ever letting a query change the data."

Start on the **Dashboard**: total revenue $283,700.56, 600 sales, 12 products, average
sale value $472.83, all calculated live from the database, plus four charts. Point out
the **Mode** selector in the sidebar: **Demo Mode** is the default and needs no AI.

## 2. Ask a question (2 min)

1. Click **Ask the AI Analyst**, then the suggestion **"Which five products generated the
   highest revenue?"**
2. Walk through the answer:
   - **Badge**: Success, 5 rows, measured run time.
   - **Explanation**: *Laptop Pro 14 has the highest revenue (102,900.00) and
     Noise-Cancelling Headphones the lowest (23,796.00).* It only states figures that are
     in the result.
   - **SQL source**: predefined SQL, no AI request made.
   - Tabs: **Results** (table), **Visualization** (sorted bars), **SQL** (the exact query
     that ran, with a copy button).
3. Open **Suggested questions** and click **"What were the monthly sales totals?"**. The
   chart is now a line because the labels are months: *highest 44,655.27 in 2025-06,
   lowest 17,119.37 in 2025-04.* The first answer stays in the conversation above.
4. Open **Query History**: both questions, newest first, marked Success.

## 3. Safety (2 min)

1. In the AI Analyst, type *"Who is our best salesperson?"* and press Enter. You get
   **Request rejected**, because Demo Mode only answers its suggested questions.
2. Open **SQL Explorer** and run `DROP TABLE sales`. You get **Request rejected**: only a
   single read-only SELECT is allowed.
3. Run `SELECT * FROM query_history`. It is rejected, because that table can't be read.
4. Run `SELECT region, COUNT(*) AS sales FROM sales GROUP BY region`. It works, and the
   data is still there.

> "Every query, whether it comes from Demo Mode, the AI, or a user, passes through four
> layers: a SQL parser check, a database-engine authorizer, a read-only connection, and
> time and row limits. The tests switch off each layer in turn to prove the others
> still hold."

## 4. AI Mode (2 min)

1. Select **AI Mode (Gemini)**. A green box confirms *Gemini model
   gemini-3.5-flash-lite is available*.
2. Ask something that isn't an example, such as *"How many units were sold in each
   region?"* A spinner shows while the model works, and the answer is labelled
   **AI-generated SQL — validated before running**.
3. Ask *"Delete all the sales data"*. Either the model declines, or its SQL is rejected by
   the safety layer. Nothing is deleted either way.

> "The AI only proposes SQL. It never touches the database directly, and the prompt is
> not relied on for safety."

### 4b. Without a key or internet

Select AI Mode: a warning explains how to get a key (or that the connection failed). Ask a question to show the clear
**Query failed** message, then switch back to Demo Mode to show it still works.

## 5. Testing (1 min)

```bash
pytest -m "not e2e" -q      # ~25 s
```

> "416 automated tests, including 14 that drive the real app in Chrome. No test needs
> the internet or a real AI model; AI Mode is tested against a fake Gemini server,
> including malicious replies. We also planted bugs on purpose to check the tests catch
> them, and that found two weak tests, which we fixed."

## Questions you may get

- **Can the AI be tricked into deleting data?** No. It is tested with malicious model
  output and prompt injection, and with each safety layer disabled in turn.
- **Is the AI's answer always right?** Not guaranteed. A query can be safe but wrong,
  so the SQL is always shown.
- **Does data leave the machine?** Only the question and the table structure are sent
  to Gemini, never the sales rows. A test checks this. The key stays in `.env`.
