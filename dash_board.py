DASHBOARD_TXT = """
## 📊 Dashboard – Local LLM Health Coach

Welcome to the **Local LLM Health Assistant**.  
This dashboard is a quick guide to what the app can do, how to use the UI, and how the backend is wired.

This app has 3000+ lines of Python code for frontend + backend logic, plus prompt engineering for dual agents.

---

### 🧭 What this app does (V0.1)

This app is a **12-week weight-loss coaching assistant** with:

- ⭐ **User accounts & profiles**  
  Each user has a local account with basic contact info and health background.

- ⭐ **Progress tracking over weeks & days**  --> will be applied in prompt
  You can log progress by week/day and revisit or edit entries later.

- **Dual-agent design: LLM-driven coaching agent**  
  A “coach” agent chats with the user using Motivational Interviewing + SMART goal style prompts.

- **Dual-agent design: Extractor / summarizer agent**  
  A second “extractor” agent summarizes recent conversations into structured JSON “goal summaries”.

- ⭐ **Goal summary + user feedback**  --> feedback will be applied in prompt
  The assistant’s goals + the user’s feedback are stored per date and fed back into future prompts.

- ⭐ **Local, file-based storage**
  Local stored database: everything lives under `user_data/` in JSON files and folders.

Right now the app can connect to a **local vLLM server** with any code for real model inference.

---

### 🧑‍💻 How to use the UI

The main workflow is:

1. **Register → Login**
2. Fill or review your **profile**
3. Log your **weekly / daily progress**
4. Use **Agent chat** to talk with the coach
5. Check **Goal summary & feedback**
6. Browse **Chat history** for past conversations

Each item in the left sidebar opens a different page:

#### 1. Login / Register

- On startup you see the **login panel**:
  - Enter username + password.
  - On successful login, the app loads your data and switches to the main dashboard.

-**“Register”**:
  - Choose a login username + password and fill required fields in profiles.
  - On successful registration:
    - A folder is created: `user_data/<username>/`
    - Initial JSON files are created for your profile, progress, goals, and chats.
    - You are redirected to the **Dashboard**.

#### 2. Progress tracking page

- Designed for a **12-week program**:
  - Select **week number** and **day number** (e.g., Week 3, Day 2).
  - The app computes the corresponding **absolute date** based on your registration date.
  - If there is existing data for that day, it is automatically loaded into the form.
  - You can edit fields (e.g., weight, notes, daily observations, any other function can be added in furture versions).

- Click **“Save progress”** to update the JSON file for that user:
  - Progress is stored in a structured JSON, indexed by week/day and by actual date.
  - Re-selecting the same week/day will reload the saved entry.

#### 4. Agent Chat page

This is the main coaching interface.

- Initial state:
    - **“Start new conversation”**
    - **“Continue unfinished conversation”**

- **Start new conversation**:
  - Creates a new conversation entry for `today` with an incremented session index (e.g., session 1, 2, 3…).
  - Marks the new conversation as **active** and not finished.

- **Continue unfinished conversation**:
  - Looks up the most recent **active** conversation for the current user.
  - Loads its history into the chatbox.
  - Re-enables the chat UI.

- **Send**:
  - Appends your user message to the active conversation.
  - Calls the **chat agent** (via `llm_reply_stub()` → vLLM or UI-test stub).
  - The agent builds a **system prompt** that includes:
    - Base coaching instructions (MI + SMART rules)
    - Your profile summary
    - Latest goal summary / feedback
  - The LLM reply is appended to the conversation history.
  - In parallel, the **extractor agent** reads:
    - Previous coach question (if any)
    - Your current answer
    - Current coach reply  
    and writes an updated **goal summary JSON** for that date.

- **End current conversation**:
  - Marks this conversation as finished in the index.
  - Saves the final history to disk (under `user_data/<username>/chats/…`).

#### 5. Chat History page

- Provides a dropdown listing all saved conversations for the logged-in user:
  - Typically formatted as `YYYY-MM-DD | session_index`.
- When you select an item:
  - The full conversation history is loaded and displayed in the chat history component.
  - A status message indicates whether the conversation is **finished** or still **active**.

This page is **read-only**: it does not modify any files.

#### 6. Goal Summary page

- Automatically loads the **most recent goal summary** for the logged-in user:
  - The summary is produced by the extractor agent and stored in `goals.json`.

- Below the summary, there is a **feedback** area:
  - You can type your reflections on how the goals went (e.g., “This week was hard because…”, “I want to shift focus to sleep.”).
  - When you click **“Save feedback”**:
    - The feedback is stored in `goals.json` under today’s date.
    - Future LLM calls read this feedback and incorporate it into the coaching context.

---
### 📂 Data layout on disk

All persistent data is stored locally under a base directory, e.g.:

```text
user_data/
  <username>/
    profile.json         # registration + profile info
    progress.json        # weekly/daily progress entries
    goals.json           # goal summaries + user feedback, keyed by date
    chats/
      index.json         # overview of all conversations (date, index, finished)
      2025-11-26_1.json  # conversation files (metadata + turn-by-turn history)
      2025-11-26_2.json
    extractor/
      ...                # optional: per-date extractor outputs, if separated

"""